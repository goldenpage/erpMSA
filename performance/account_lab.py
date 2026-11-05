#!/usr/bin/env python3
"""Account(로그인·회원가입·토큰 갱신) 대규모 부하 실험.

performance/lab.py의 일회용 실험 프로젝트(erpmsa-sprint4-lab)만 사용한다. 실제 ERP .env·DB·볼륨에 접근하지 않는다.
설계와 판정 기준: docs/load-test-design.md §13
"""
import argparse
import datetime as dt
import hashlib
import json
import re
import secrets
import subprocess
import threading
import time
import urllib.parse
import urllib.request

import lab

FIXTURE = lab.RESULTS / 'account-fixture.json'
DATASET = lab.RESULTS / 'account-dataset.json'
RUNS = lab.RESULTS / 'account-runs.json'
DOMAIN = 'load.example.com'
FIXTURE_EMAIL = 'acct-fixture@' + DOMAIN
FIXTURE_BID = '8000000000'
TOPIC = 'account.lifecycle.v1'
CHUNK = 100_000
GENERATOR = 'account-seed-v1'
MAX_ACCOUNTS = 5_000_000
SCENARIOS = ['me', 'login', 'login-attack', 'register', 'register-dup', 'session']
REGISTERING = {'register': 'reg', 'register-dup': 'dup'}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


# ---------- 순수 함수 (test_account_lab.py에서 검사) ----------

def status_of(seq):
    """account.js statusOf와 같은 규칙. 1% SUSPENDED, 1% PENDING."""
    r = seq % 100
    return 'SUSPENDED' if r == 0 else 'PENDING' if r == 1 else 'ACTIVE'


def expected_status_counts(accounts):
    suspended = accounts // 100
    pending = accounts // 100 + (1 if accounts % 100 >= 1 else 0)
    return {'ACTIVE': accounts - suspended - pending, 'PENDING': pending, 'SUSPENDED': suspended}


def chunks(total, size=CHUNK):
    return [(start, min(start + size - 1, total)) for start in range(1, total + 1, size)]


def seed_sql(start, end, hash_value):
    if not re.fullmatch(r'\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}', hash_value):
        raise ValueError('Unexpected BCrypt hash format')
    # 상태·날짜·이메일·사업자번호는 seq에서 결정적으로 만든다. b_id 9xxxxxxxxx 범위는 seed 전용이다.
    return f"""INSERT INTO mydb.account
        (b_id,created_at,email,marketing_agreed,name,phone,pw_hash,review_status,role,
         store_category,store_name,store_type,updated_at)
        SELECT CONCAT('9',LPAD(seq,9,'0')),
            TIMESTAMPADD(SECOND,-seq*30,'2026-10-01 00:00:00'),
            CONCAT('acct-',LPAD(seq,8,'0'),'@{DOMAIN}'), MOD(seq,2), CONCAT('Load ',seq), '01012345678',
            '{hash_value}', CASE MOD(seq,100) WHEN 0 THEN 'SUSPENDED' WHEN 1 THEN 'PENDING' ELSE 'ACTIVE' END,
            'ROLE_USER','TEST','Load Store','RETAIL',
            TIMESTAMPADD(SECOND,-seq*30,'2026-10-01 00:00:00')
        FROM mydb.seq_{start}_to_{end};"""


def parse_tsv(text):
    return [line.split('\t') for line in text.splitlines() if line.strip()]


def reconcile(accounts, outbox, kafka_records):
    """accounts: [accountId], outbox: [(eventId, accountId, status)], kafka_records: [payload dict]."""
    account_ids = set(accounts)
    per_account = {}
    for event_id, account_id, _ in outbox:
        per_account.setdefault(account_id, []).append(event_id)
    outbox_ids = {event_id for event_id, _, _ in outbox}
    published = {event_id for event_id, _, status in outbox if status == 'PUBLISHED'}
    run_records = [r for r in kafka_records if r.get('accountId') in account_ids]
    seen = {}
    for record in run_records:
        seen[record.get('eventId')] = seen.get(record.get('eventId'), 0) + 1
    statuses = {}
    for _, _, status in outbox:
        statuses[status] = statuses.get(status, 0) + 1
    return {
        'accounts': len(account_ids),
        'outboxEvents': len(outbox),
        'outboxStatus': statuses,
        'accountsWithoutEvent': len(account_ids - set(per_account)),
        'accountsWithMultipleEvents': sum(1 for ids in per_account.values() if len(ids) > 1),
        'kafkaRecords': len(run_records),
        'kafkaUniqueEvents': len(seen),
        'kafkaDuplicateRecords': len(run_records) - len(seen),
        'publishedMissingInKafka': len(published - set(seen)),
        'kafkaUnknownEvents': len(set(seen) - outbox_ids),
    }


def verdict(summary, created, outbox_pending):
    failures = []
    if created is not None and created != summary['accounts']:
        failures.append(f"k6 201 count {created} != account rows {summary['accounts']}")
    for key in ['accountsWithoutEvent', 'accountsWithMultipleEvents', 'publishedMissingInKafka', 'kafkaUnknownEvents']:
        if summary[key]:
            failures.append(f'{key}={summary[key]}')
    if outbox_pending:
        failures.append(f'outbox PENDING not drained: {outbox_pending}')
    # 중복 발행은 at-least-once 결과로 별도 보고한다(eventId로 소비자 중복 제거 가능). 누락과 구분한다.
    return {'result': 'FAIL' if failures else 'PASS', 'failures': failures,
            'duplicatePublications': summary['kafkaDuplicateRecords']}


def k6_counter(summary, name):
    metric = summary.get('metrics', {}).get(name)
    if not metric:
        return 0
    values = metric.get('values', metric)
    return int(values.get('count', 0))


def parse_info(text):
    info = {}
    for line in text.splitlines():
        if ':' in line and not line.startswith('#'):
            key, value = line.strip().split(':', 1)
            info[key] = value
    keys = 0
    for value in [v for k, v in info.items() if re.fullmatch(r'db\d+', k)]:
        keys += int(dict(part.split('=') for part in value.split(',')).get('keys', 0))
    pick = ['used_memory', 'used_memory_rss', 'maxmemory', 'maxmemory_policy', 'evicted_keys',
            'instantaneous_ops_per_sec', 'connected_clients', 'rejected_connections']
    return {**{k: info.get(k) for k in pick}, 'keys': keys}


def validate_stages(text):
    if not re.fullmatch(r'\d{1,5}:\d{1,4}[smh](,\d{1,5}:\d{1,4}[smh]){0,29}', text):
        raise ValueError('stages must look like 50:2m,100:2m')
    for part in text.split(','):
        if int(part.split(':')[0]) > 20000:
            raise ValueError('stage target above 20000/s')
    return text


# ---------- 실험실 조작 ----------

def run_state():
    return json.loads(RUNS.read_text()) if RUNS.exists() else {'next': 0, 'runs': {}}


def allocate_run(label, scenario):
    state = run_state()
    if label in state['runs']:
        raise SystemExit(f'Label {label} already used. Use a new label.')
    number = state['next']
    if number > 99:
        raise SystemExit('Registration run numbers exhausted. Recreate the disposable lab.')
    prefix = REGISTERING[scenario]
    if lab.sql(f"SELECT COUNT(*) FROM mydb.account WHERE email LIKE '{prefix}-r{number:02d}-%';") != '0':
        raise SystemExit('Run number already has accounts. Refusing to mix runs.')
    state['next'] = number + 1
    state['runs'][label] = {'runNo': number, 'scenario': scenario, 'emailPrefix': f'{prefix}-r{number:02d}-'}
    lab.save('account-runs', state)
    return number


def seed(accounts):
    lab.verify_lab()
    if lab.sql(f"SELECT COUNT(*) FROM mydb.account WHERE email LIKE 'acct-%@{DOMAIN}';") != '0':
        raise SystemExit('Accounts already seeded. Reuse the dataset or recreate the disposable lab.')
    lab.wait_gateway()
    password = secrets.token_urlsafe(24)
    status, body = lab.request('/account/auth/register', 'POST', {
        'email': FIXTURE_EMAIL, 'businessId': FIXTURE_BID, 'password': password, 'name': 'Load Fixture',
        'phone': '01012345678', 'storeName': 'Load Fixture', 'storeType': 'RETAIL', 'storeCategory': 'TEST',
        'marketingAgreed': False})
    if status != 201:
        raise SystemExit(f'Fixture registration failed: HTTP {status}')
    # 앱이 만든 BCrypt 해시를 그대로 복사한다. 비용(cost)이 같으므로 로그인 계산량은 실제와 같다.
    hash_value = lab.sql(f"SELECT pw_hash FROM mydb.account WHERE email='{FIXTURE_EMAIL}';")
    started = time.monotonic()
    for start, end in chunks(accounts):
        lab.sql(seed_sql(start, end, hash_value))
        print(f'seeded {end}/{accounts}', flush=True)
    lab.sql('ANALYZE TABLE mydb.account;')
    seconds = time.monotonic() - started
    rows = dict(parse_tsv(lab.sql(
        f"SELECT review_status, COUNT(*) FROM mydb.account WHERE email LIKE 'acct-%@{DOMAIN}' AND email <> '{FIXTURE_EMAIL}' GROUP BY review_status;")))
    counts = {k: int(v) for k, v in rows.items()}
    if counts != expected_status_counts(accounts):
        raise SystemExit(f'Seed verification failed: {counts}')
    status, _ = lab.request('/account/auth/login', 'POST', {'email': f'acct-{2:08d}@{DOMAIN}', 'password': password})
    if status != 200:
        raise SystemExit(f'Seeded account login check failed: HTTP {status}')
    sizes = parse_tsv(lab.sql("SELECT data_length, index_length FROM information_schema.tables WHERE table_schema='mydb' AND table_name='account';"))
    lab.save('account-fixture', {'password': password, 'domain': DOMAIN, 'accounts': accounts})
    FIXTURE.chmod(0o600)
    lab.save('account-dataset', {'generator': GENERATOR, 'accounts': accounts, 'statusCounts': counts,
        'statusRule': 'seq%100==0 SUSPENDED, seq%100==1 PENDING, else ACTIVE', 'bcryptCost': hash_value[4:6],
        'dataBytes': int(sizes[0][0]), 'indexBytes': int(sizes[0][1]), 'seedSeconds': round(seconds, 1), 'at': now()})
    print(f'Seeded {accounts} accounts in {seconds:.0f}s. Fixture password is stored only in {FIXTURE}.')


class Sampler(threading.Thread):
    """부하 중 5초마다 Outbox 상태·Redis 메모리·계정 수를 기록한다. 실패한 표본은 이유와 함께 남긴다."""

    def __init__(self, interval=5):
        super().__init__(daemon=True)
        self.interval, self.samples, self.stop = interval, [], threading.Event()

    def sample(self):
        point = {'at': now()}
        try:
            point['outbox'] = {k: int(v) for k, v in parse_tsv(lab.sql(
                'SELECT status, COUNT(*) FROM mydb.account_outbox_event GROUP BY status;'))}
        except Exception as exception:
            point['outboxError'] = type(exception).__name__
        try:
            # 앱이 노출하는 Outbox 지표를 그대로 읽는다. DB 시간대 해석 차이를 피한다.
            with urllib.request.urlopen('http://127.0.0.1:19090/api/v1/query?' + urllib.parse.urlencode(
                    {'query': 'max(account_outbox_oldest_age_seconds)'}), timeout=5) as response:
                result = json.load(response)['data']['result']
            point['outboxOldestAgeSeconds'] = float(result[0]['value'][1]) if result else None
        except Exception as exception:
            point['outboxAgeError'] = type(exception).__name__
        try:
            info = lab.compose('exec', '-T', 'redis', 'redis-cli', 'INFO', capture=True).stdout
            point['redis'] = parse_info(info)
        except Exception as exception:
            point['redisError'] = type(exception).__name__
        self.samples.append(point)

    def run(self):
        while not self.stop.is_set():
            self.sample()
            self.stop.wait(self.interval)


PROM_QUERIES = {
    'accountCpu': 'process_cpu_usage{job="account-service"}',
    'gatewayCpu': 'process_cpu_usage{job="gateway-server"}',
    'accountPoolActive': 'hikaricp_connections_active{job="account-service"}',
    'accountPoolPending': 'hikaricp_connections_pending{job="account-service"}',
    'accountRps': 'sum by(instance,uri,status)(rate(http_server_requests_seconds_count{job="account-service"}[30s]))',
    'accountP95': 'histogram_quantile(0.95,sum by(instance,uri,le)(rate(http_server_requests_seconds_bucket{job="account-service"}[30s])))',
    'gatewayP95': 'histogram_quantile(0.95,sum by(le)(rate(http_server_requests_seconds_bucket{job="gateway-server"}[30s])))',
    'accountGcPause': 'rate(jvm_gc_pause_seconds_sum{job="account-service"}[30s])',
    'accountHeap': 'sum by(instance)(jvm_memory_used_bytes{job="account-service",area="heap"})',
    'outboxPending': 'account_outbox_pending',
}


def prometheus_window(start, end, step=5):
    """실행 구간의 서버 지표 시계열. 수집 주기(15초)보다 촘촘한 step은 같은 표본을 반복한다."""
    output = {'start': start, 'end': end, 'step': step, 'series': {}}
    for name, query in PROM_QUERIES.items():
        params = urllib.parse.urlencode({'query': query, 'start': start, 'end': end, 'step': step})
        try:
            with urllib.request.urlopen('http://127.0.0.1:19090/api/v1/query_range?' + params, timeout=10) as response:
                output['series'][name] = json.load(response)['data']['result']
        except Exception as exception:
            output['series'][name] = {'unavailable': type(exception).__name__}
    return output


def k6_env(args, run_no):
    env = {'BASE_URL': args.base_url, 'SCENARIO': args.scenario, 'LABEL': args.label, 'RUN_NO': run_no,
           'FIXTURE_FILE': f'/work/{lab.RESULTS.relative_to(lab.HERE)}/account-fixture.json',
           'RESULTS_DIR': f'/work/{lab.RESULTS.relative_to(lab.HERE)}', 'MAX_VUS': args.max_vus}
    optional = {'RATE': args.rate, 'STAGES': args.stages, 'DURATION': args.duration, 'VUS': args.vus,
                'NORMAL_RATE': args.normal_rate, 'ATTACK_KIND': args.attack_kind, 'ATTACK_DELAY': args.attack_delay,
                'LOGIN_SET': args.login_set, 'DUP_SIZE': args.dup_size, 'DUP_MODE': args.dup_mode,
                'REFRESH_EVERY': args.refresh_every, 'THINK': args.think, 'REPLAY_PCT': args.replay_pct,
                'RACE_PCT': args.race_pct, 'ATTACK_IPS': args.attack_ips, 'CLIENT_IPS': args.client_ips}
    env.update({k: v for k, v in optional.items() if v is not None})
    return {k: str(v) for k, v in env.items()}


def run(args):
    lab.verify_lab()
    if not FIXTURE.exists():
        raise SystemExit('Run account_lab.py seed first.')
    run_no = allocate_run(args.label, args.scenario) if args.scenario in REGISTERING else 0
    lab.capture(args.label + '-before')
    sampler = Sampler()
    sampler.start()
    started = now()
    command = ['run', '--rm', '--no-deps']
    for key, value in k6_env(args, run_no).items():
        command += ['-e', f'{key}={value}']
    if args.prometheus_rw:
        command += ['-e', 'K6_PROMETHEUS_RW_SERVER_URL=http://prometheus:9090/api/v1/write',
                    '-e', 'K6_PROMETHEUS_RW_TREND_STATS=p(50),p(95),p(99),max']
    outputs = ['-o', 'experimental-prometheus-rw'] if args.prometheus_rw else []
    if not args.no_raw:
        # 요청 단위 원시 기록: 단계별·태그별 분석(account_report.py)에 쓴다.
        command += ['-e', 'K6_CSV_TIME_FORMAT=unix_milli']
        outputs += ['-o', f'csv=/work/{lab.RESULTS.relative_to(lab.HERE)}/{args.label}.csv.gz']
    command += ['k6', 'run'] + outputs + ['/work/account.js']
    started_epoch = time.time()
    result = lab.compose(*command, check=False)
    finished = now()
    sampler.stop.set()
    sampler.join(timeout=30)
    lab.save(args.label + '-samples', sampler.samples)
    lab.save(args.label + '-prom', prometheus_window(started_epoch, time.time() + 15))
    lab.capture(args.label + '-after')
    lab.save(args.label + '-conditions', {
        'scenario': args.scenario, 'runNo': run_no, 'exitCode': result.returncode, 'startedAt': started,
        'finishedAt': finished, 'k6Env': {k: v for k, v in k6_env(args, run_no).items() if k != 'FIXTURE_FILE'},
        'workloadSha256': hashlib.sha256((lab.HERE / 'account.js').read_bytes()).hexdigest(),
        'datasetSha256': hashlib.sha256(DATASET.read_bytes()).hexdigest()})
    print(f'k6 exit code {result.returncode}. Registration runs need: account_lab.py check --label {args.label}')
    raise SystemExit(result.returncode)


def kafka_records(topic):
    output = lab.compose('exec', '-T', 'kafka', '/opt/kafka/bin/kafka-console-consumer.sh',
        '--bootstrap-server', 'kafka:9092', '--topic', topic, '--from-beginning', '--timeout-ms', '20000',
        capture=True, check=False)
    records = []
    for line in output.stdout.splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def check(args):
    lab.verify_lab()
    state = run_state()['runs'].get(args.label)
    if not state:
        raise SystemExit('Unknown registration label. check applies only to register/register-dup runs.')
    prefix = state['emailPrefix']
    started = time.monotonic()
    while True:
        pending = int(lab.sql(f"""SELECT COUNT(*) FROM mydb.account_outbox_event e JOIN mydb.account a
            ON a.id = CAST(e.aggregate_id AS UNSIGNED) WHERE a.email LIKE '{prefix}%' AND e.status <> 'PUBLISHED';"""))
        if pending == 0 or time.monotonic() - started > args.drain_timeout:
            break
        time.sleep(5)
    drain_seconds = time.monotonic() - started
    accounts = [int(row[0]) for row in parse_tsv(lab.sql(f"SELECT id FROM mydb.account WHERE email LIKE '{prefix}%';"))]
    outbox = [(row[0], int(row[1]), row[2]) for row in parse_tsv(lab.sql(f"""SELECT e.event_id, a.id, e.status
        FROM mydb.account_outbox_event e JOIN mydb.account a ON a.id = CAST(e.aggregate_id AS UNSIGNED)
        WHERE a.email LIKE '{prefix}%';"""))]
    summary = reconcile(accounts, outbox, kafka_records(args.topic))
    k6 = json.loads((lab.RESULTS / (args.label + '.json')).read_text())
    if state['scenario'] == 'register':
        created = k6_counter(k6, 'account_register_created')
    else:
        created = k6_counter(k6, 'account_dup_group_ok') + k6_counter(k6, 'account_dup_group_bad')
        summary['dupGroupBad'] = k6_counter(k6, 'account_dup_group_bad')
    result = verdict(summary, created, pending)
    if summary.get('dupGroupBad'):
        result['result'] = 'FAIL'
        result['failures'].append(f"duplicate groups without exactly one 201: {summary['dupGroupBad']}")
    report = {'label': args.label, 'checkedAt': now(), 'drainWaitSeconds': round(drain_seconds, 1),
              'k6Created': created, 'summary': summary, 'verdict': result,
              'note': 'drainWaitSeconds는 check 시작 시점부터 잰다. 부하 종료 직후 실행해야 적체 해소 시간으로 해석할 수 있다.'}
    lab.save(args.label + '-check', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['result'] == 'PASS' else 1)


# 재배포 측정 대상: (Compose 서비스, Gateway 경유 측정 요청, 토큰 필요). 정상 응답은 하류 인스턴스가 직접 낸 것이어야 한다.
# account: BCrypt가 없는 GET /account/auth/login(정상 405).
# foodmaterials: 실험실 계정 토큰으로 GET /foodmaterials(정상 200). 토큰이 없으면 Gateway JWT 필터가 401을 내
#   하류까지 가지 않으므로 측정이 되지 않는다(2026-11-04 첫 측정에서 확인).
REDEPLOY_TARGETS = {
    'account': ('account-service', '/account/auth/login', False),
    'foodmaterials': ('foodmaterials-service', '/foodmaterials?page=0&size=20', True),
}


def summarize_probe(samples, healthy_at=None):
    """재배포 중 표본 [(t, status)]을 상태별 건수와 실패 구간으로 요약한다. status 0은 연결 실패·시간 초과."""
    ok = {200, 401, 405}
    counts = {}
    for _, status in samples:
        counts[str(status)] = counts.get(str(status), 0) + 1
    failures = [t for t, status in samples if status not in ok]
    result = {'requests': len(samples), 'statusCounts': counts, 'failures': len(failures),
              'firstFailureAt': round(failures[0], 2) if failures else None,
              'lastFailureAt': round(failures[-1], 2) if failures else None}
    if healthy_at is not None:
        after = [t for t, status in samples if t >= healthy_at and status in ok]
        result['newInstanceHealthyAt'] = round(healthy_at, 2)
        result['firstSuccessAfterHealthy'] = round(after[0], 2) if after else None
        later_failures = [t for t in failures if t >= healthy_at]
        result['failuresAfterHealthy'] = len(later_failures)
        result['recoveryLagSeconds'] = round(max(later_failures) - healthy_at, 2) if later_failures else 0.0
    return result


def reconcile_disposals(records, ledger, initial, on_hand):
    """재배포 중 낸 폐기의 최종 상태와 FoodMaterials 원장을 맞춘다.
    records: 최종 폐기 기록 [{disposalId, status, quantity}], ledger: DISPOSAL 원장 [{requestId, quantityDelta}].
    완료 폐기마다 원장 한 줄(requestId=DISPOSAL-<disposalId>)이 있고, 중복 차감이 없고, 현재고가 맞아야 한다."""
    completed = {r['disposalId']: r['quantity'] for r in records if r['status'] == 'COMPLETED'}
    request_ids = [m['requestId'] for m in ledger]
    ledger_ids = {rid[len('DISPOSAL-'):] for rid in request_ids if rid.startswith('DISPOSAL-')}
    statuses = {}
    for r in records:
        statuses[r['status']] = statuses.get(r['status'], 0) + 1
    checks = {
        'ledgerMatchesCompleted': ledger_ids == set(completed),
        'noDuplicateDeduction': len(request_ids) == len(set(request_ids)),
        'ledgerQuantityMatches': -sum(m['quantityDelta'] for m in ledger) == sum(completed.values()),
        'onHandMatches': on_hand == initial - sum(completed.values()),
    }
    return {'disposals': len(records), 'finalStatusCounts': statuses, 'ledgerRows': len(ledger),
            'initialQuantity': initial, 'onHandQuantity': on_hand, 'checks': checks,
            'result': 'PASS' if all(checks.values()) else 'FAIL'}


def service_containers(service='account-service'):
    ids = lab.compose('ps', '-q', service, capture=True).stdout.split()
    inspected = json.loads(subprocess.check_output(['docker', 'inspect', *ids], text=True)) if ids else []
    return {c['Id']: c for c in inspected}


def redeploy(args):
    """재배포 중 Gateway 경유 요청의 실패를 잰다. rolling: 새 인스턴스를 띄운 뒤 옛 인스턴스를 SIGTERM으로 내린다.
    recreate: 인스턴스 하나를 새 컨테이너로 바꾼다(중단 불가피). 측정 요청은 REDEPLOY_TARGETS(--service)."""
    service, path, needs_token = REDEPLOY_TARGETS[args.service]
    lab.verify_lab()
    lab.wait_gateway()
    samples, stop = [], threading.Event()
    token = fixture_token(args.label) if needs_token else None
    disposal = disposal_fixture(args.label, token) if args.disposal_rate else None
    disposal_samples = []
    started = time.monotonic()

    def probe():
        while not stop.is_set():
            t = time.monotonic() - started
            try:
                status, _ = lab.request(path, token=token)
            except Exception:
                status = 0
            samples.append((t, status))
            stop.wait(1 / args.probe_rate)

    def disposal_probe():
        # 폐기마다 새 requestId. Gateway → Disposals → (Eureka) FoodMaterials 재고 차감 경로를 지난다.
        number = 0
        while not stop.is_set():
            number += 1
            t = time.monotonic() - started
            body = {'requestId': f'RD-{args.label}-{number}', 'foodMaterialId': disposal['foodMaterialId'],
                    'quantity': 1, 'reason': '재배포 측정'}
            try:
                status, payload = lab.request('/disposals', 'POST', body, disposal['token'])
                view = json.loads(payload) if payload else {}
            except Exception:
                status, view = 0, {}
            disposal_samples.append((t, status, view.get('disposalId'), view.get('status')))
            stop.wait(1 / args.disposal_rate)

    thread = threading.Thread(target=probe, daemon=True)
    thread.start()
    disposal_thread = threading.Thread(target=disposal_probe, daemon=True) if disposal else None
    if disposal_thread:
        disposal_thread.start()
    events = []
    healthy_at = None
    try:
        stop.wait(5)
        before = service_containers(service)
        if args.mode == 'rolling':
            target = len(before) + 1
            lab.compose('up', '-d', '--no-build', '--no-deps', '--no-recreate', '--wait', '--wait-timeout', '240',
                        '--scale', f'{service}={target}', service)
            events.append(('new-instance-healthy', time.monotonic() - started))
            # 새 인스턴스가 Gateway에 반영될 시간을 둔 뒤 가장 오래된 인스턴스를 내린다.
            stop.wait(args.settle)
            oldest = sorted(before.values(), key=lambda c: c['Created'])[0]
            events.append(('old-stop-begin', time.monotonic() - started))
            subprocess.run(['docker', 'stop', '--time', str(args.stop_timeout), oldest['Id']], check=True, stdout=subprocess.DEVNULL)
            events.append(('old-stopped', time.monotonic() - started))
            subprocess.run(['docker', 'rm', oldest['Id']], check=True, stdout=subprocess.DEVNULL)
        else:
            events.append(('recreate-begin', time.monotonic() - started))
            lab.compose('up', '-d', '--no-build', '--no-deps', '--force-recreate', '--wait', '--wait-timeout', '240',
                        service)
            healthy_at = time.monotonic() - started
            events.append(('new-instance-healthy', healthy_at))
        stop.wait(args.observe)
    finally:
        stop.set()
        thread.join(timeout=10)
        if disposal_thread:
            disposal_thread.join(timeout=10)
    report = {'service': service, 'probePath': path, 'mode': args.mode, 'at': now(), 'probeRatePerSecond': args.probe_rate, 'settleSeconds': args.settle,
              'stopTimeoutSeconds': args.stop_timeout, 'events': [(name, round(t, 2)) for name, t in events],
              'summary': summarize_probe(samples, healthy_at),
              'timeline': [(round(t, 2), status) for t, status in samples if status not in (200, 401, 405)][:500]}
    if disposal:
        report['disposals'] = settle_disposals(disposal, disposal_samples)
    lab.save(args.label + '-redeploy', report)
    print(json.dumps({k: report[k] for k in ('service', 'mode', 'events', 'summary', 'disposals') if k in report},
                     ensure_ascii=False, indent=1))


DISPOSAL_INITIAL = 100_000


def fixture_token(label):
    """실험실 전용 계정을 Gateway로 만들고 Access Token을 받는다. businessId 5로 시작(다른 시드와 겹치지 않음)."""
    email, password = f'redeploy-{label.lower()}@{DOMAIN}', secrets.token_urlsafe(24)
    status, _ = lab.request('/account/auth/register', 'POST', {
        'email': email, 'businessId': '5' + str(secrets.randbelow(10**9)).zfill(9), 'password': password,
        'name': 'Redeploy', 'phone': '01012345678', 'storeName': 'Redeploy Lab', 'storeType': 'RETAIL',
        'storeCategory': 'TEST', 'marketingAgreed': False})
    if status != 201:
        raise SystemExit(f'Fixture registration failed: HTTP {status}')
    status, payload = lab.request('/account/auth/login', 'POST', {'email': email, 'password': password})
    if status != 200:
        raise SystemExit(f'Fixture login failed: HTTP {status}')
    return json.loads(payload)['accessToken']


def disposal_fixture(label, token):
    """실험실 전용 식자재·재고를 만든다."""
    status, payload = lab.request('/foodmaterials', 'POST', {'sku': f'RD-{label}', 'name': '재배포 측정', 'unitPrice': 1000}, token)
    if status != 201:
        raise SystemExit(f'Food material fixture failed: HTTP {status}')
    material = json.loads(payload)['foodMaterialId']
    status, _ = lab.request('/foodmaterials/inventories', 'POST', {'foodMaterialId': material, 'initialQuantity': DISPOSAL_INITIAL}, token)
    if status != 201:
        raise SystemExit(f'Inventory fixture failed: HTTP {status}')
    return {'token': token, 'foodMaterialId': material}


def settle_disposals(fixture, samples, attempts=5):
    """PENDING 폐기를 같은 폐기 식별자로 재시도한 뒤 원장과 맞춘다. 성공으로 간주하지 않는다."""
    token, material = fixture['token'], fixture['foodMaterialId']
    created = {}
    counts = {}
    for _, status, disposal_id, _ in samples:
        counts[str(status)] = counts.get(str(status), 0) + 1
        if disposal_id:
            created[disposal_id] = True
    retried = 0
    for _ in range(attempts):
        pending = []
        for disposal_id in created:
            status, payload = lab.request(f'/disposals/{disposal_id}', token=token)
            if status == 200 and json.loads(payload)['status'] == 'PENDING':
                pending.append(disposal_id)
        if not pending:
            break
        for disposal_id in pending:
            lab.request(f'/disposals/{disposal_id}/retry', 'POST', token=token)
            retried += 1
        time.sleep(2)
    records = []
    for disposal_id in created:
        status, payload = lab.request(f'/disposals/{disposal_id}', token=token)
        view = json.loads(payload)
        records.append({'disposalId': disposal_id, 'status': view['status'], 'quantity': view['quantity']})
    ledger, page = [], 0
    while True:
        status, payload = lab.request(f'/foodmaterials/inventories/{material}/movements?page={page}&size=100', token=token)
        body = json.loads(payload)
        ledger += [m for m in body['movements'] if m['movementType'] == 'DISPOSAL']
        page += 1
        if page >= body['totalPages']:
            break
    _, payload = lab.request(f'/foodmaterials/inventories/{material}', token=token)
    on_hand = json.loads(payload)['onHandQuantity']
    result = reconcile_disposals(records, ledger, DISPOSAL_INITIAL, on_hand)
    result.update({'requests': len(samples), 'firstResponseCounts': counts,
                   'firstResponsePending': sum(1 for *_, st in samples if st == 'PENDING'),
                   'unansweredOrNoRecord': sum(1 for _, _, d, _ in samples if not d), 'retryCalls': retried,
                   'timeline': [(round(t, 2), st, ds) for t, st, _, ds in samples if st != 200][:200]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=['seed', 'run', 'check', 'scale', 'kafka', 'redeploy'])
    parser.add_argument('--accounts', type=int, default=1_000_000)
    parser.add_argument('--scenario', choices=SCENARIOS, default='login')
    parser.add_argument('--label', default='account-run')
    parser.add_argument('--rate', type=int)
    parser.add_argument('--stages')
    parser.add_argument('--duration')
    parser.add_argument('--vus', type=int)
    parser.add_argument('--max-vus', type=int, default=500)
    parser.add_argument('--normal-rate', type=int)
    parser.add_argument('--attack-kind', choices=['wrongpw', 'unknown'])
    parser.add_argument('--attack-delay')
    parser.add_argument('--login-set', choices=['active', 'all'])
    parser.add_argument('--dup-size', type=int)
    parser.add_argument('--dup-mode', choices=['email', 'bid'])
    parser.add_argument('--refresh-every', type=int)
    parser.add_argument('--think', type=float)
    parser.add_argument('--replay-pct', type=int)
    parser.add_argument('--race-pct', type=int)
    parser.add_argument('--attack-ips', type=int, help='login-attack 공격자 모의 IP 수(기본 4)')
    parser.add_argument('--client-ips', choices=['on', 'off'], help='모의 클라이언트 IP(X-Forwarded-For) 사용 여부(기본 on)')
    parser.add_argument('--base-url', default='http://gateway-server:7070',
                        choices=['http://gateway-server:7070', 'http://account-service:7071'])
    parser.add_argument('--prometheus-rw', action='store_true')
    parser.add_argument('--no-raw', action='store_true', help='요청 단위 CSV 기록을 끈다(장시간 실행의 파일 크기 절감)')
    parser.add_argument('--replicas', type=int, choices=[1, 2, 3], default=2)
    parser.add_argument('--action', choices=['stop', 'start'])
    parser.add_argument('--topic', default=TOPIC)
    parser.add_argument('--drain-timeout', type=int, default=900)
    parser.add_argument('--mode', choices=['rolling', 'recreate'], default='rolling')
    parser.add_argument('--service', choices=sorted(REDEPLOY_TARGETS), default='account', help='redeploy 대상(기본 account)')
    parser.add_argument('--disposal-rate', type=int, default=0,
                        help='redeploy --service foodmaterials: 초당 폐기 요청 수(0=끔). 끝나면 PENDING을 재시도하고 원장과 맞춘다')
    parser.add_argument('--probe-rate', type=int, default=20)
    parser.add_argument('--settle', type=int, default=30, help='rolling: 새 인스턴스 기동 후 옛 인스턴스를 내리기까지 대기(초)')
    parser.add_argument('--stop-timeout', type=int, default=30, help='docker stop 유예(초). 넘으면 SIGKILL')
    parser.add_argument('--observe', type=int, default=60, help='작업 후 관찰 시간(초)')
    args = parser.parse_args()

    if not re.fullmatch('[A-Za-z0-9_-]{1,64}', args.label):
        parser.error('Unsafe label')
    if not re.fullmatch(r'[a-z0-9.-]{1,100}', args.topic):
        parser.error('Unsafe topic')
    if not 100 <= args.accounts <= MAX_ACCOUNTS:
        parser.error(f'accounts must be 100..{MAX_ACCOUNTS}')
    for name in ['duration', 'attack_delay']:
        value = getattr(args, name)
        if value is not None and not re.fullmatch(r'[1-9]\d{0,3}[smh]', value):
            parser.error(f'--{name.replace("_", "-")} must look like 90s, 10m, 2h')
    try:
        if args.stages:
            validate_stages(args.stages)
    except ValueError as error:
        parser.error(str(error))
    for name, low, high in [('rate', 1, 20000), ('normal_rate', 1, 20000), ('vus', 1, 50000), ('max_vus', 1, 50000),
                            ('dup_size', 2, 10), ('refresh_every', 1, 3600), ('replay_pct', 0, 100), ('race_pct', 0, 100),
                            ('attack_ips', 1, 65536)]:
        value = getattr(args, name)
        if value is not None and not low <= value <= high:
            parser.error(f'--{name.replace("_", "-")} must be {low}..{high}')
    if args.disposal_rate and (args.service != 'foodmaterials' or not 1 <= args.disposal_rate <= 20):
        parser.error('--disposal-rate is 1..20 and only for --service foodmaterials')
    if not lab.ENV.exists():
        parser.error('Run performance/lab.py prepare first')

    if args.command == 'seed':
        seed(args.accounts)
    elif args.command == 'run':
        run(args)
    elif args.command == 'check':
        check(args)
    elif args.command == 'scale':
        lab.verify_lab()
        lab.compose('up', '-d', '--no-deps', '--wait', '--wait-timeout', '180',
                    '--scale', f'account-service={args.replicas}', 'account-service')
    elif args.command == 'redeploy':
        redeploy(args)
    elif args.command == 'kafka':
        if not args.action:
            parser.error('--action stop|start is required')
        lab.verify_lab()
        lab.compose(args.action, 'kafka')
        lab.save(f'kafka-{args.action}', {'at': now()})


if __name__ == '__main__':
    main()
