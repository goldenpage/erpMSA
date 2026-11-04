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


def k6_env(args, run_no):
    env = {'BASE_URL': args.base_url, 'SCENARIO': args.scenario, 'LABEL': args.label, 'RUN_NO': run_no,
           'FIXTURE_FILE': f'/work/{lab.RESULTS.relative_to(lab.HERE)}/account-fixture.json',
           'RESULTS_DIR': f'/work/{lab.RESULTS.relative_to(lab.HERE)}', 'MAX_VUS': args.max_vus}
    optional = {'RATE': args.rate, 'STAGES': args.stages, 'DURATION': args.duration, 'VUS': args.vus,
                'NORMAL_RATE': args.normal_rate, 'ATTACK_KIND': args.attack_kind, 'ATTACK_DELAY': args.attack_delay,
                'LOGIN_SET': args.login_set, 'DUP_SIZE': args.dup_size, 'DUP_MODE': args.dup_mode,
                'REFRESH_EVERY': args.refresh_every, 'THINK': args.think, 'REPLAY_PCT': args.replay_pct,
                'RACE_PCT': args.race_pct}
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
    command += ['k6', 'run'] + (['-o', 'experimental-prometheus-rw'] if args.prometheus_rw else []) + ['/work/account.js']
    result = lab.compose(*command, check=False)
    finished = now()
    sampler.stop.set()
    sampler.join(timeout=30)
    lab.save(args.label + '-samples', sampler.samples)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=['seed', 'run', 'check', 'scale', 'kafka'])
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
    parser.add_argument('--base-url', default='http://gateway-server:7070',
                        choices=['http://gateway-server:7070', 'http://account-service:7071'])
    parser.add_argument('--prometheus-rw', action='store_true')
    parser.add_argument('--replicas', type=int, choices=[1, 2, 3], default=2)
    parser.add_argument('--action', choices=['stop', 'start'])
    parser.add_argument('--topic', default=TOPIC)
    parser.add_argument('--drain-timeout', type=int, default=900)
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
                            ('dup_size', 2, 10), ('refresh_every', 1, 3600), ('replay_pct', 0, 100), ('race_pct', 0, 100)]:
        value = getattr(args, name)
        if value is not None and not low <= value <= high:
            parser.error(f'--{name.replace("_", "-")} must be {low}..{high}')
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
    elif args.command == 'kafka':
        if not args.action:
            parser.error('--action stop|start is required')
        lab.verify_lab()
        lab.compose(args.action, 'kafka')
        lab.save(f'kafka-{args.action}', {'at': now()})


if __name__ == '__main__':
    main()
