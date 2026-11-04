#!/usr/bin/env python3
"""account_lab.py 실행 결과를 단계(stage)·시간 구간·요청 종류별로 집계한다.

입력: results/<label>.csv.gz(k6 요청 단위 기록), <label>-conditions.json, <label>-prom.json
출력: 표준출력 Markdown 표, results/<label>-report.json
판정 기준: docs/load-test-design.md §7.1 (오류율, p95 배수, 누락, 달성률)
"""
import argparse
import csv
import gzip
import json
import math
import re
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / 'results'
DURATION_UNITS = {'s': 1, 'm': 60, 'h': 3600}


def seconds(text):
    return int(text[:-1]) * DURATION_UNITS[text[-1]]


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    # nearest-rank: ceil(q/100 × n)번째 값
    index = min(len(ordered) - 1, max(0, math.ceil(q / 100 * len(ordered)) - 1))
    return ordered[index]


def tags(row):
    extra = dict(part.split('=', 1) for part in row.get('extra_tags', '').split('&') if '=' in part)
    return f"{row.get('name', '')}|{extra.get('kind', '-')}"


def profile(stages_text, start_rate):
    """ramping-arrival-rate의 목표율 곡선: 각 단계에서 이전 값→단계 값으로 선형 변화한다."""
    points, cursor, rate = [(0, start_rate)], 0, start_rate
    for part in stages_text.split(','):
        target, duration = part.split(':')
        cursor += seconds(duration)
        rate = int(target)
        points.append((cursor, rate))
    return points


def expected_rate(points, start, end, steps=200):
    def at(t):
        for (t0, r0), (t1, r1) in zip(points, points[1:]):
            if t0 <= t <= t1:
                return r0 if t1 == t0 else r0 + (r1 - r0) * (t - t0) / (t1 - t0)
        return points[-1][1]
    return sum(at(start + (end - start) * (i + 0.5) / steps) for i in range(steps)) / steps


def stage_windows(stages_text, settle, start_rate=1):
    """단계별 [시작+settle, 끝) 구간. target은 그 구간의 평균 목표율이다(선형 증가 반영)."""
    points = profile(stages_text, start_rate)
    windows, cursor = [], 0
    for part in stages_text.split(','):
        target, duration = part.split(':')
        length = seconds(duration)
        start, end = cursor + min(settle, length // 2), cursor + length
        windows.append({'label': f'{target}/s', 'target': round(expected_rate(points, start, end), 2),
                        'start': start, 'end': end})
        cursor += length
    return windows


def fixed_windows(total, size):
    return [{'label': f'{t}-{min(t + size, total)}s', 'target': None, 'start': t, 'end': min(t + size, total)}
            for t in range(0, total, size)]


def load_rows(path):
    with gzip.open(path, 'rt', newline='') as handle:
        yield from csv.DictReader(handle)


def aggregate(rows, windows, origin):
    buckets = [{'requests': {}, 'dropped': 0} for _ in windows]
    for row in rows:
        metric = row['metric_name']
        if metric not in ('http_req_duration', 'dropped_iterations'):
            continue
        if row.get('group') == '::setup':
            continue
        offset = (int(row['timestamp']) - origin) / 1000
        for index, window in enumerate(windows):
            if window['start'] <= offset < window['end']:
                bucket = buckets[index]
                if metric == 'dropped_iterations':
                    bucket['dropped'] += int(float(row['metric_value']))
                else:
                    item = bucket['requests'].setdefault(tags(row), {'durations': [], 'unexpected': 0, 'status': {}})
                    item['durations'].append(float(row['metric_value']))
                    item['unexpected'] += row.get('expected_response') == 'false'
                    item['status'][row['status']] = item['status'].get(row['status'], 0) + 1
                break
    return buckets


def prom_stats(prom, name, start, end):
    series = prom.get('series', {}).get(name)
    if not isinstance(series, list):
        return None
    values = [float(v) for s in series for t, v in s.get('values', []) if start <= float(t) < end and v not in ('NaN', '+Inf')]
    return {'mean': sum(values) / len(values), 'max': max(values)} if values else None


def summarize(label, window_size, settle, baseline_p95):
    conditions = json.loads((RESULTS / f'{label}-conditions.json').read_text())
    prom_path = RESULTS / f'{label}-prom.json'
    prom = json.loads(prom_path.read_text()) if prom_path.exists() else {}
    rows = list(load_rows(RESULTS / f'{label}.csv.gz'))
    stamps = [int(r['timestamp']) for r in rows if r['metric_name'] == 'http_reqs' and r.get('group') != '::setup']
    if not stamps:
        raise SystemExit('No request rows in CSV.')
    origin, total = min(stamps), (max(stamps) - min(stamps)) / 1000 + 1
    env = conditions['k6Env']
    # login-attack·session은 시나리오가 둘이거나 VU 기반이라 단계=요청률 대응이 없다. 고정 구간으로 본다.
    staged = env.get('STAGES') and env.get('SCENARIO') not in ('login-attack', 'session')
    windows = stage_windows(env['STAGES'], settle, int(env.get('START_RATE', 1))) if staged else fixed_windows(int(total), window_size)
    if not staged and env.get('RATE') and env.get('SCENARIO') not in ('login-attack', 'session'):
        for window in windows:
            window['target'] = int(env['RATE'])
    buckets = aggregate(rows, windows, origin)
    report = []
    for window, bucket in zip(windows, buckets):
        span = max(1e-9, window['end'] - window['start'])
        groups = {}
        for key, item in sorted(bucket['requests'].items()):
            count = len(item['durations'])
            groups[key] = {'count': count, 'rps': round(count / span, 2),
                           'p50': percentile(item['durations'], 50), 'p95': percentile(item['durations'], 95),
                           'p99': percentile(item['durations'], 99), 'unexpected': item['unexpected'],
                           'status': item['status']}
        requests = sum(g['count'] for g in groups.values())
        unexpected = sum(g['unexpected'] for g in groups.values())
        all_durations = [d for item in bucket['requests'].values() for d in item['durations']]
        p95 = percentile(all_durations, 95)
        # 서버 지표는 k6 첫 요청 시각(origin)을 기준으로 같은 구간을 자른다.
        server = {name: prom_stats(prom, name, origin / 1000 + window['start'], origin / 1000 + window['end'])
                  for name in ['accountCpu', 'gatewayCpu', 'accountPoolPending', 'accountPoolActive', 'outboxPending']}
        flags = []
        if requests and unexpected / requests >= 0.01:
            flags.append('error>=1%')
        if baseline_p95 and p95 and p95 > 3 * baseline_p95:
            flags.append('p95>3x')
        if bucket['dropped']:
            flags.append('dropped')
        achieved = requests / span
        if window['target'] and achieved < 0.95 * window['target'] * (int(env.get('DUP_SIZE', 1)) if env.get('SCENARIO') == 'register-dup' else 1):
            flags.append('achieved<95%')
        report.append({'window': window['label'], 'start': window['start'], 'end': window['end'], 'target': window['target'],
                       'achievedRps': round(achieved, 2), 'goodputRps': round((requests - unexpected) / span, 2), 'p95': p95, 'unexpected': unexpected, 'dropped': bucket['dropped'],
                       'saturated': bool(flags), 'flags': flags, 'groups': groups, 'server': server})
    knee = None
    for row in report:
        if row['saturated']:
            break
        knee = row
    result = {'label': label, 'scenario': env.get('SCENARIO'), 'settleSeconds': settle, 'baselineP95': baseline_p95,
              'windows': report, 'kneeWindow': knee['window'] if knee else None,
              'kneeAchievedRps': knee['achievedRps'] if knee else None,
              'note': '같은 호스트에서 부하 발생기와 서비스를 함께 실행한 결과는 T1 조건으로만 해석한다.'}
    (RESULTS / f'{label}-report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def fmt(value, digits=1):
    return '-' if value is None else f'{value:.{digits}f}'


def print_markdown(result):
    print(f"### {result['label']} ({result['scenario']})\n")
    print('| 구간 | 목표/s | 전송/s | 성공/s | p95 ms | 기대 외 응답 | 누락 | Account CPU 평균/최대 | 풀 대기 최대 | 판정 |')
    print('|---|---:|---:|---:|---:|---:|---:|---:|---:|---|')
    for row in result['windows']:
        cpu = row['server'].get('accountCpu')
        pending = row['server'].get('accountPoolPending')
        print(f"| {row['window']} | {row['target'] or '-'} | {fmt(row['achievedRps'])} | {fmt(row['goodputRps'])} | {fmt(row['p95'])} | {row['unexpected']} | "
              f"{row['dropped']} | {fmt(cpu and cpu['mean'] * 100, 0)}% / {fmt(cpu and cpu['max'] * 100, 0)}% | "
              f"{fmt(pending and pending['max'], 0)} | {', '.join(row['flags']) or 'OK'} |")
    print(f"\n포화 전 마지막 구간: {result['kneeWindow']} (달성 {result['kneeAchievedRps']}/s)\n")
    keys = sorted({k for row in result['windows'] for k in row['groups']})
    if len(keys) > 1:
        print('| 구간 | 요청 종류 | 건수 | p50 | p95 | p99 | 상태 |')
        print('|---|---|---:|---:|---:|---:|---|')
        for row in result['windows']:
            for key in keys:
                g = row['groups'].get(key)
                if g:
                    print(f"| {row['window']} | {key} | {g['count']} | {fmt(g['p50'])} | {fmt(g['p95'])} | {fmt(g['p99'])} | {g['status']} |")
        print()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('labels', nargs='+')
    parser.add_argument('--window', type=int, default=30, help='STAGES가 없을 때 구간 길이(초)')
    parser.add_argument('--settle', type=int, default=15, help='각 단계 시작 후 제외할 전환 구간(초)')
    parser.add_argument('--baseline-p95', type=float, help='A0 기준선 p95(ms). p95>3x 판정에 사용')
    args = parser.parse_args()
    for label in args.labels:
        if not re.fullmatch('[A-Za-z0-9_-]{1,64}', label):
            parser.error('Unsafe label')
        print_markdown(summarize(label, args.window, args.settle, args.baseline_p95))


if __name__ == '__main__':
    main()
