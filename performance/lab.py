#!/usr/bin/env python3
"""A fixed-name, disposable Compose lab. Never reads the application's .env or DB."""
import argparse
import datetime as dt
import json
import hashlib
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'performance'
RESULTS = HERE / 'results'
ENV = HERE / '.env'
PROJECT = 'erpmsa-sprint4-lab'
GATEWAY = 'http://127.0.0.1:17070'

def compose(*args, capture=False, input=None, check=True):
    command = ['docker', 'compose', '--env-file', str(ENV), '-p', PROJECT,
               '-f', str(ROOT / 'compose.yaml'), '-f', str(ROOT / 'compose.performance.yaml'), *args]
    return subprocess.run(command, cwd=ROOT, text=True, input=input,
                          capture_output=capture, check=check)

def verify_lab():
    if not ENV.is_file() or 'LAB_PROJECT=' + PROJECT not in ENV.read_text():
        raise SystemExit('Run prepare first. A dedicated lab environment is required.')
    ids = compose('ps', '-q', 'mariadb', capture=True).stdout.split()
    if len(ids) != 1:
        raise SystemExit('A running disposable lab database is required.')
    inspected = json.loads(subprocess.check_output(['docker', 'inspect', ids[0]], text=True))[0]
    if inspected['Config']['Labels'].get('com.docker.compose.project') != PROJECT:
        raise SystemExit('Refusing to access a database outside the lab.')
    if '/var/lib/mysql' not in (inspected['HostConfig'].get('Tmpfs') or {}):
        raise SystemExit('Refusing to access a persistent database.')

def verify_volume_names():
    config = json.loads(compose('config', '--format', 'json', capture=True).stdout)
    for volume in config.get('volumes', {}).values():
        if volume.get('external') or not volume.get('name', '').startswith(PROJECT + '-'):
            raise SystemExit('Refusing lab lifecycle action with non-lab volume names.')

def sql(query):
    verify_lab()
    return compose('exec', '-T', 'mariadb', 'sh', '-ec',
        'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb --user=root --batch --skip-column-names',
        capture=True, input=query).stdout.strip()

def request(path, method='GET', body=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token: headers['Authorization'] = 'Bearer ' + token
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(GATEWAY + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()

def save(label, data):
    RESULTS.mkdir(exist_ok=True)
    fd = os.open(RESULTS / (label + '.json'), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(data, output, ensure_ascii=False, indent=2)

def wait_gateway():
    # A TCP healthcheck does not prove that Eureka/LB caches have converged.
    consecutive = 0
    users_file = RESULTS / 'users.json'
    token = json.loads(users_file.read_text())[0]['token'] if users_file.exists() else None
    for _ in range(180):
        try:
            ready = request('/account/auth/login')[0] == 405
            if token:
                ready = ready and request('/items?page=0&size=20', token=token)[0] == 200
        except (OSError, urllib.error.URLError):
            ready = False
        consecutive = consecutive + 1 if ready else 0
        if consecutive >= 10:
            return
        time.sleep(1)
    raise RuntimeError('Gateway account route did not stabilize')

def prepare():
    HERE.mkdir(exist_ok=True)
    RESULTS.mkdir(exist_ok=True)
    if ENV.exists():
        print('Lab environment already exists; keys and secrets preserved.')
        return
    key_dir = HERE / 'secrets/jwt'
    if not (key_dir / 'private/lab-k1.pem').exists():
        subprocess.run([str(ROOT / 'scripts/generate-jwt-keys.sh'), 'lab-k1', str(key_dir)], check=True)
    values = {
        'LAB_PROJECT': PROJECT, 'DB_PASSWORD': secrets.token_hex(24),
        'GRAFANA_ADMIN_PASSWORD': secrets.token_hex(24), 'GRAFANA_SECRET_KEY': secrets.token_hex(32),
        'JWT_SIGNING_KEY_ID': 'lab-k1', 'JWT_PUBLIC_KEYS_HOST_DIR': str(key_dir / 'public'),
        'JWT_PRIVATE_KEY_HOST_FILE': str(key_dir / 'private/lab-k1.pem'),
        'JWT_ACCESS_TTL': '4h', 'FLYWAY_BASELINE_ON_MIGRATE': 'false',
    }
    fd = os.open(ENV, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(''.join(f'{key}={value}\n' for key, value in values.items()))
    print('Prepared isolated lab. Gateway=17070 Prometheus=19090 Grafana=13000')

def seed(rows):
    verify_lab()
    if sql('SELECT COUNT(*) FROM itemdb.item;') != '0':
        raise SystemExit('Lab already seeded. Use the existing dataset or recreate the disposable lab.')
    for attempt in range(60):
        try:
            status, _ = request('/account/auth/login')
            if status == 405: break
        except (OSError, urllib.error.URLError): pass
        time.sleep(2)
    else: raise SystemExit('Gateway discovery did not become ready.')
    users = []
    for number, multiplier in enumerate([1, 1, 2, 2, 5, 10], 1):
        password = secrets.token_urlsafe(24)
        email = f'load-{number}@example.com'
        status, _ = request('/account/auth/register', 'POST', {
            'email': email, 'businessId': f'{number:010}', 'password': password,
            'name': f'Load {number}', 'phone': '01012345678', 'storeName': 'Load Test',
            'storeType': 'RETAIL', 'storeCategory': 'TEST', 'marketingAgreed': False})
        if status != 201: raise SystemExit(f'Fixture registration failed: HTTP {status}')
        status, payload = request('/account/auth/login', 'POST', {'email': email, 'password': password})
        if status != 200: raise SystemExit(f'Fixture login failed: HTTP {status}')
        token = json.loads(payload)['accessToken']
        status, payload = request('/account/auth/me', token=token)
        if status != 200: raise SystemExit('Fixture identity could not be verified.')
        account = json.loads(payload)['accountId']
        count = rows * multiplier
        sql(f"""INSERT INTO itemdb.item
            (account_id,sku,name,description,unit_price,status,version,created_at,updated_at)
            SELECT {account},CONCAT('P-{account}-',LPAD(seq,8,'0')),CONCAT('Item ',seq),REPEAT('x',200),
                1000 + MOD(seq,10000),IF(MOD(seq,5)=0,'INACTIVE','ACTIVE'),0,
                TIMESTAMPADD(SECOND,-seq,'2026-01-01'),TIMESTAMPADD(SECOND,-seq,'2026-01-01')
            FROM itemdb.seq_1_to_{count};""")
        users.append({'accountId': account, 'token': token, 'rows': count})
    save('users', users)
    (RESULTS / 'users.json').chmod(0o600)
    save('dataset', {'rows': sum(u['rows'] for u in users), 'accounts': len(users),
        'rowsPerAccount': [u['rows'] for u in users], 'activeRatio': 0.8,
        'descriptionBytes': 200, 'seed': 'deterministic-sequence-v1'})
    print(f'Seeded {len(users)} accounts and {sum(u["rows"] for u in users)} items in temporary lab DB.')

def capture(label):
    verify_lab()
    queries = {
        'up': 'up', 'rps': 'sum by(job,instance)(rate(http_server_requests_seconds_count[1m]))',
        'p95': 'histogram_quantile(0.95,sum by(job,instance,le)(rate(http_server_requests_seconds_bucket[1m])))',
        'connections': 'hikaricp_connections_active', 'connectionWaiters': 'hikaricp_connections_pending',
        'heap': 'jvm_memory_used_bytes{area="heap"}', 'cpu': 'process_cpu_usage',
        'gcPause': 'rate(jvm_gc_pause_seconds_sum[1m])',
        'outboxPending': 'account_outbox_pending', 'outboxOldestAge': 'account_outbox_oldest_age_seconds',
    }
    output = {'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'queries': {}}
    for name, query in queries.items():
        try:
            with urllib.request.urlopen('http://127.0.0.1:19090/api/v1/query?' + urllib.parse.urlencode({'query': query}), timeout=5) as response:
                output['queries'][name] = json.load(response)
        except Exception as exception: output['queries'][name] = {'unavailable': type(exception).__name__}
    ids = compose('ps', '-aq', capture=True).stdout.split()
    inspected = json.loads(subprocess.check_output(['docker', 'inspect', *ids], text=True)) if ids else []
    output['containers'] = [{'name': c['Name'], 'imageId': c['Image'], 'state': c['State'],
        'memoryLimit': c['HostConfig']['Memory'], 'nanoCpus': c['HostConfig']['NanoCpus']} for c in inspected]
    # Never serialize Config.Env or token-bearing request headers.
    output['stats'] = compose('stats', '--no-stream', '--format', 'json', capture=True, check=False).stdout
    save(label + '-metrics', output)
    logs = compose('logs','--no-color','--since','5m','--tail','1000','item-service',capture=True,check=False)
    (RESULTS / (label + '-item-gc.log')).write_text(logs.stdout)

def query_plan(label):
    users = json.loads((RESULTS / 'users.json').read_text())
    largest = users[-1]
    plans = []
    for status in ['ACTIVE', 'INACTIVE', None]:
        for page in [0, max(1, largest['rows'] // 1000)]:
            where = f"account_id={largest['accountId']}" + (f" AND status='{status}'" if status else '')
            for kind, query in [('list', f'SELECT * FROM itemdb.item WHERE {where} ORDER BY created_at DESC,id DESC LIMIT 20 OFFSET {page * 20}'),
                                ('count', f'SELECT COUNT(*) FROM itemdb.item WHERE {where}')]:
                samples = []
                for _ in range(5):
                    raw = sql('ANALYZE FORMAT=JSON ' + query + ';')
                    samples.append(json.loads(raw.replace('\\n','\n').replace('\\t','\t')))
                plans.append({'status': status, 'page': page, 'kind': kind, 'samples': samples})
    save(label + '-sql', plans)

def outage(service, seconds):
    verify_lab()
    wait_gateway()
    capture('before-' + service + '-outage')
    compose('stop', service)
    try:
        registration = None
        if service == 'kafka':
            number = int(time.time()) % 10**10
            status, _ = request('/account/auth/register', 'POST', {
                'email': f'outage-{number}@example.com', 'businessId': f'{number:010}',
                'password': secrets.token_urlsafe(24), 'name': 'Outage', 'phone': '01012345678',
                'storeName': 'Outage Lab', 'storeType': 'RETAIL', 'storeCategory': 'TEST', 'marketingAgreed': False})
            if status != 201: raise RuntimeError(f'Registration during broker outage failed: {status}')
            registration = status
        # Probe already discovered instances while the dependency is down.
        token = json.loads((RESULTS / 'users.json').read_text())[0]['token']
        statuses = {}
        started = time.monotonic()
        while time.monotonic() - started < seconds:
            try: status, _ = request('/items?page=0&size=20', token=token)
            except (OSError, urllib.error.URLError): status = 0
            statuses[str(status)] = statuses.get(str(status), 0) + 1
            time.sleep(0.2)
        result = {'durationSeconds':time.monotonic()-started, 'statuses':statuses}
        if service == 'kafka':
            result['registrationStatus'] = registration
            result['pendingWhileDown'] = int(sql("SELECT COUNT(*) FROM mydb.account_outbox_event WHERE status='PENDING';"))
        save(service + '-outage-probes', result)
        capture('during-' + service + '-outage')
    finally:
        compose('start', service)
    if service == 'kafka':
        started = time.monotonic()
        for _ in range(90):
            pending = int(sql("SELECT COUNT(*) FROM mydb.account_outbox_event WHERE status='PENDING';"))
            missing = int(sql('''SELECT COUNT(*) FROM mydb.account_outbox_event o
                LEFT JOIN auditdb.audit_event a ON o.event_id=a.event_id WHERE a.event_id IS NULL;'''))
            if pending == 0 and missing == 0: break
            time.sleep(2)
        else: raise RuntimeError('Outbox/audit recovery deadline exceeded')
        save('kafka-recovery', {'pending': pending, 'missingAudit': missing, 'recoverySeconds': time.monotonic()-started})
    capture('after-' + service + '-outage')

def kill_one(seconds):
    verify_lab()
    wait_gateway()
    ids = compose('ps','-q','item-service',capture=True).stdout.split()
    if len(ids) < 2: raise SystemExit('Scale item-service to at least two replicas first.')
    target = ids[-1]
    capture('before-item-kill')
    subprocess.run(['docker','kill','--signal','KILL',target],check=True,stdout=subprocess.DEVNULL)
    try:
        token = json.loads((RESULTS / 'users.json').read_text())[0]['token']
        statuses = {}
        started = time.monotonic()
        while time.monotonic()-started < seconds:
            try: status, _ = request('/items?page=0&size=20',token=token)
            except (OSError,urllib.error.URLError): status=0
            statuses[str(status)] = statuses.get(str(status),0)+1
            time.sleep(0.2)
        inspected=json.loads(subprocess.check_output(['docker','inspect',target],text=True))[0]
        save('item-kill',{'statuses':statuses,'durationSeconds':time.monotonic()-started,
            'injectedSignal':'SIGKILL','state':inspected['State']})
        capture('during-item-kill')
    finally:
        subprocess.run(['docker','start',target],check=True,stdout=subprocess.DEVNULL)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare','up','seed','run','capture','sql','index','scale','outage','kill-one','down'])
    parser.add_argument('--label', default='run')
    parser.add_argument('--rate', type=int, default=40)
    parser.add_argument('--duration', default='60s')
    parser.add_argument('--profile', choices=['mixed','fixed'], default='mixed')
    parser.add_argument('--direct', action='store_true')
    parser.add_argument('--rows', type=int, default=10000)
    parser.add_argument('--replicas', type=int, choices=[1,2,3], default=2)
    parser.add_argument('--service', choices=['kafka','eureka-server','item-service'], default='kafka')
    parser.add_argument('--seconds', type=int, default=20)
    parser.add_argument('--state', choices=['baseline','indexed'], default='indexed')
    args = parser.parse_args()
    if not re.fullmatch('[A-Za-z0-9_-]+',args.label): parser.error('Unsafe label')
    if not 1 <= args.rows <= 100000 or not 1 <= args.rate <= 1000 or not 1 <= args.seconds <= 60:
        parser.error('rows/rate/seconds out of bounded lab range')
    if not re.fullmatch(r'[1-9][0-9]{0,2}s',args.duration): parser.error('Duration must be 1s..999s')
    if args.command == 'prepare': prepare(); return
    if not ENV.exists(): parser.error('Run prepare first')
    if args.command == 'up':
        verify_volume_names(); compose('up','-d','--build','--wait','--wait-timeout','180')
    elif args.command == 'seed': seed(args.rows)
    elif args.command == 'run':
        verify_lab()
        base = 'http://item-service:7073' if args.direct else 'http://gateway-server:7070'
        capture(args.label + '-before')
        result = compose('run','--rm','--no-deps','-e',f'BASE_URL={base}','-e',f'RATE={args.rate}',
            '-e',f'DURATION={args.duration}','-e',f'PROFILE={args.profile}','-e',f'LABEL={args.label}',
            'k6','run','/work/items.js', check=False)
        save(args.label + '-conditions', {'rate':args.rate,'duration':args.duration,'profile':args.profile,
            'base':base,'exitCode':result.returncode,'at':dt.datetime.now(dt.timezone.utc).isoformat(),
            'preAllocatedVUs':150,'maxVUs':150,
            'workloadSha256':hashlib.sha256((HERE/'items.js').read_bytes()).hexdigest(),
            'datasetSha256':hashlib.sha256((RESULTS/'dataset.json').read_bytes()).hexdigest()})
        capture(args.label + '-after')
        raise SystemExit(result.returncode)
    elif args.command == 'capture': capture(args.label)
    elif args.command == 'sql': query_plan(args.label)
    elif args.command == 'index':
        exists = int(sql("SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema='itemdb' AND table_name='item' AND index_name='idx_item_account_status_created';")) > 0
        if args.state == 'baseline' and exists:
            sql('DROP INDEX idx_item_account_status_created ON itemdb.item;')
        elif args.state == 'indexed' and not exists:
            sql('CREATE INDEX idx_item_account_status_created ON itemdb.item(account_id,status,created_at,id);')
        save('index-state', {'state':args.state,'at':dt.datetime.now(dt.timezone.utc).isoformat()})
    elif args.command == 'scale':
        verify_lab(); compose('up','-d','--no-deps','--wait','--wait-timeout','180',
                             '--scale',f'item-service={args.replicas}','item-service')
    elif args.command == 'outage': outage(args.service,args.seconds)
    elif args.command == 'kill-one': kill_one(args.seconds)
    elif args.command == 'down':
        # Only this hard-coded disposable project is removed; application volumes are untouched.
        verify_volume_names()
        compose('down','-v','--remove-orphans')

if __name__ == '__main__': main()
