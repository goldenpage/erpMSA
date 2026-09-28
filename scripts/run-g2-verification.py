#!/usr/bin/env python3
"""Build and verify three local JARs against a uniquely owned tmpfs DB (G2 only)."""
import argparse
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('g1', ROOT/'scripts/run-g1-verification.py')
g1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g1)
MODULES = ('FoodMaterialsService', 'MenusService', 'DisposalsService')
SCHEMAS = ('itemdb', 'inventorydb', 'menusdb', 'disposalsdb')
TABLES = {'item': 'itemdb', 'inventory': 'inventorydb', 'stock_movement': 'inventorydb',
          'menu': 'menusdb', 'disposal': 'disposalsdb'}


class Failure(AssertionError):
    pass


def check(condition, message):
    if not condition:
        raise Failure(message)


def validate_database(item, run_id, before):
    labels = item['Config'].get('Labels') or {}
    if item['Id'] in before or labels.get(g1.LABEL) != run_id or labels.get('erpmsa.verification.stage') != 'G2':
        raise RuntimeError('Database ownership not established')
    if item['Config']['Image'] != 'mariadb:10.11' or '/var/lib/mysql' not in item['HostConfig'].get('Tmpfs', {}):
        raise RuntimeError('Database must use MariaDB with tmpfs')
    if any(m['Type'] in ('bind', 'volume') for m in item.get('Mounts', [])):
        raise RuntimeError('Persistent/host mount refused')
    bindings = item['NetworkSettings']['Ports'].get('3306/tcp') or []
    if len(bindings) != 1 or bindings[0]['HostIp'] != '127.0.0.1':
        raise RuntimeError('Database must bind exclusively to loopback')
    return int(bindings[0]['HostPort'])


def read_only_sql(statement):
    if not statement.lstrip().upper().startswith('SELECT ') or any(c in statement for c in ';\n\r\\'):
        raise ValueError('Only one read-only SELECT is allowed')
    return 'START TRANSACTION READ ONLY;\n' + statement + ';\nROLLBACK;\n'


def response_body(status, raw, record):
    # Save status and raw evidence before JSON parsing can fail.
    record['status'] = status
    try:
        body = json.loads(raw) if raw else {}
        if not isinstance(body, dict):
            raise ValueError('Expected JSON object')
    except (ValueError, UnicodeError):
        record['rawResponse'] = raw.decode('utf-8', errors='replace')
        raise Failure('Non-JSON/object HTTP response; status='+str(status))
    record['response'] = body
    return body


def aggregate_status(scenarios):
    states = [entry['status'] for entry in scenarios]
    return 'PASS' if states and all(s == 'PASS' for s in states) else 'FAIL' if 'FAIL' in states else 'BLOCKED'


class Run:
    def __init__(self, offline):
        self.run_id = secrets.token_hex(6)
        self.artifact = ROOT/'.verification'/self.run_id
        self.artifact.mkdir(parents=True, mode=0o700)
        self.temporary = Path(tempfile.mkdtemp(prefix='erpmsa-g2-', dir='/private/tmp' if Path('/private/tmp').exists() else None))
        self.credentials = Path(tempfile.mkdtemp(prefix='erpmsa-g2-credentials-', dir=str(self.temporary.parent)))
        self.application_dir = self.temporary/'applications'
        self.application_dir.mkdir()
        self.env = g1.sanitized_environment(os.environ)
        self.offline = offline
        self.processes, self.logs, self.secrets = [], [], []
        self.container = None
        self.docker_command = None
        self.before = set()
        self.http_lock = threading.Lock()
        self.concurrent_context = threading.local()
        self.apps = {}
        self.manifest = dict(runId=self.run_id, scope='G2: 3 real JARs, direct HTTP, synthetic JWT; no G3/G4/remote CI',
                             status='RUNNING', startedAt=g1.now(), scenarios=[], builds=[], jars={})
        self.scenario = 'preflight'
        self.save()

    def clean_text(self, text):
        for secret in self.secrets:
            text = text.replace(secret, '[REDACTED]')
        return g1.redact(text)

    def save(self):
        g1.save_json(self.artifact/'manifest.json', self.manifest)

    def command(self, args, input=None, timeout=60):
        return subprocess.run(args, input=input, env=self.env, cwd=self.temporary,
                              text=True, capture_output=True, check=True, timeout=timeout).stdout.strip()

    def docker(self, *args, input=None, timeout=60):
        return self.command([*self.docker_command, *args], input, timeout)

    def ids(self):
        return set(self.docker('ps', '-aq', '--no-trunc').split())

    def inspect_owned(self):
        item = json.loads(self.docker('inspect', self.container))[0]
        validate_database(item, self.run_id, self.before)
        return item

    def preflight(self):
        self.manifest['commit'] = g1.output(['git', 'rev-parse', 'HEAD'], self.env)
        self.manifest['changes'] = g1.output(['git', 'status', '--short'], self.env).splitlines()
        self.manifest['sourceHashes'] = g1.source_hashes(self.env)
        # Require a successful G1 on identical application/build/test inputs. New G2 tools are allowed.
        g2_files = {'scripts/run-g2-verification.py', 'scripts/g2_scenarios.py', 'scripts/test_g2_verification.py'}
        inputs = {n: h for n, h in self.manifest['sourceHashes'].items() if n not in g2_files}
        candidates = []
        for p in (ROOT/'.verification').glob('*/manifest.json'):
            data = json.loads(p.read_text())
            if data.get('status') == 'PASS' and data.get('scope', '').startswith('G1 only'):
                previous = {n: h for n, h in data.get('sourceHashes', {}).items() if n not in g2_files}
                if previous == inputs:
                    candidates.append((data['finishedAt'], str(p)))
        if not candidates:
            raise RuntimeError('No PASS G1 manifest matches current application/build/test inputs')
        self.manifest['g1Evidence'] = sorted(candidates)[-1][1]
        gradle = Path(self.env['HOME'])/'.gradle'
        overrides = [p for p in [gradle/'gradle.properties', gradle/'init.gradle', gradle/'init.gradle.kts'] if p.exists()]
        overrides += [p for p in (gradle/'init.d').glob('*') if p.is_file()]
        if overrides:
            raise RuntimeError('User Gradle overrides must be absent')
        context = self.command(['docker', 'context', 'show'])
        endpoint = json.loads(self.command(['docker', 'context', 'inspect', context]))[0]['Endpoints']['docker']['Host']
        if not endpoint.startswith('unix:///') or not stat.S_ISSOCK(Path(endpoint[7:]).stat().st_mode):
            raise RuntimeError('Local Unix Docker endpoint required')
        self.docker_command = ['docker', '--host', endpoint]
        self.before = self.ids()
        self.manifest.update(dockerContext=context, dockerVersion=self.docker('version', '--format', '{{.Server.Version}}'),
                             preexistingContainerIds=sorted(self.before))
        java_home = self.command(['/usr/libexec/java_home', '-v', '21']) if Path('/usr/libexec/java_home').exists() else str(Path(shutil.which('java')).resolve().parent.parent)
        self.java = java_home + '/bin/java'
        version = subprocess.run([self.java, '-version'], capture_output=True, text=True, check=True).stderr
        if 'version "21.' not in version:
            raise RuntimeError('Java 21 required')
        self.manifest['javaVersion'] = version.splitlines()[0]
        self.env['JAVA_HOME'] = java_home
        self.lsof = shutil.which('lsof')
        if not self.lsof:
            raise RuntimeError('lsof is required to verify listening JVM ownership')
        self.manifest['g0'] = [g1.output(['python3', str(ROOT/'scripts/verify-service-architecture.py'), *flags], self.env)
                               for flags in ([], ['--ci'], ['--performance'])]
        self.save()

    def build(self):
        for module in MODULES:
            print('BUILD ' + module, flush=True)
            started = time.time()
            args = ['sh', str(ROOT/module/'gradlew'), '-p', str(ROOT/module), 'bootJar', '--no-daemon',
                    '--rerun-tasks', '--no-build-cache', '--console=plain',
                    '-Dorg.gradle.jvmargs=-Xmx512m -Derpmsa.verification.run=' + self.run_id]
            if self.offline:
                args.append('--offline')
            raw = self.temporary/(module+'-build.log')
            with raw.open('w') as log:
                process = subprocess.Popen(args, cwd=self.temporary, env=self.env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                self.processes.append(process)
                try:
                    code = process.wait(timeout=600)
                finally:
                    g1.stop_process(process)
                    leaks = g1.stop_marked_processes(self.run_id)
                    (self.artifact/raw.name).write_text(self.clean_text(raw.read_text(errors='replace')))
            self.manifest['builds'].append(dict(module=module, exitCode=code, command=args, processLeak=leaks))
            self.save()
            if code or leaks:
                raise RuntimeError(module + ' build failed or process cleanup incomplete')
            jars = [p for p in (ROOT/module/'build/libs').glob('*.jar') if not p.name.endswith('-plain.jar')]
            if len(jars) != 1 or jars[0].stat().st_mtime < started:
                raise RuntimeError('Missing, ambiguous or stale JAR: ' + module)
            frozen = self.temporary/jars[0].name
            shutil.copyfile(jars[0], frozen)
            self.manifest['jars'][module] = dict(path=str(frozen), sha256=hashlib.sha256(frozen.read_bytes()).hexdigest())
        self.save()

    def database(self):
        password = secrets.token_hex(24)
        self.secrets.append(password)
        self.password = password
        verifier_password = secrets.token_hex(24)
        self.secrets.append(verifier_password)
        envfile = self.credentials/'database.env'
        envfile.write_text(f'MARIADB_ROOT_PASSWORD={password}\nMARIADB_USER=account\nMARIADB_PASSWORD={password}\nMARIADB_DATABASE=itemdb\nERPMSA_VERIFY_PASSWORD={verifier_password}\n')
        name = 'erpmsa-g2-' + self.run_id
        # Keep the intended name before creation so partial docker-run failures can still be cleaned safely.
        self.container = name
        try:
            self.docker('run', '-d', '--name', name, '--label', g1.LABEL+'='+self.run_id,
                        '--label', 'erpmsa.verification.stage=G2', '--tmpfs', '/var/lib/mysql:rw',
                        '-p', '127.0.0.1::3306', '--env-file', str(envfile), 'mariadb:10.11', timeout=180)
        finally:
            envfile.unlink(missing_ok=True)
        item = self.inspect_owned()
        self.db_port = validate_database(item, self.run_id, self.before)
        self.manifest['database'] = dict(id=item['Id'], name=name, imageId=item['Image'], port=self.db_port,
                                         tmpfs=item['HostConfig']['Tmpfs'], schemas=list(SCHEMAS))
        self.save()
        for _ in range(90):
            try:
                self.docker('exec', name, 'healthcheck.sh', '--connect', '--innodb_initialized', timeout=5)
                break
            except subprocess.CalledProcessError:
                time.sleep(1)
        else:
            raise RuntimeError('Isolated database readiness timeout')
        self.inspect_owned()
        sql = ''.join(f"CREATE DATABASE {schema}; GRANT ALL ON {schema}.* TO 'account'@'%';\n" for schema in SCHEMAS[1:])
        sql += f"CREATE USER 'verifier'@'localhost' IDENTIFIED BY '{verifier_password}';\n"
        sql += ''.join(f"GRANT SELECT ON {schema}.* TO 'verifier'@'localhost';\n" for schema in SCHEMAS)
        self.docker('exec', '-i', name, 'sh', '-ec', 'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb -uroot', input=sql)

    def start_apps(self):
        self.kid = 'it-' + self.run_id
        self.command(['bash', str(ROOT/'scripts/generate-jwt-keys.sh'), self.kid, str(self.credentials/'keys')])
        self.command(['bash', str(ROOT/'scripts/generate-jwt-keys.sh'), 'wrong', str(self.credentials/'untrusted')])
        shutil.copytree(self.credentials/'keys/public', self.temporary/'public')
        self.tokens = {account: self.token(account) for account in (101, 202)}
        ports = set()
        self.ports = {}
        for module in MODULES:
            while True:
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', 0))
                    port = sock.getsockname()[1]
                if port not in ports:
                    ports.add(port)
                    self.ports[module] = port
                    break
        common = dict(PATH=self.env.get('PATH', '/usr/bin:/bin'), LANG='en_US.UTF-8',
                      JWT_ISSUER='g2-fixture', JWT_AUDIENCE='g2-fixture',
                      JWT_PUBLIC_KEY_DIRECTORY=str(self.temporary/'public'),
                      EUREKA_CLIENT_ENABLED='false', SPRING_CLOUD_DISCOVERY_ENABLED='false',
                      FOOD_MATERIAL_DISCOVERY_ENABLED='false',
                      FOOD_MATERIAL_SERVICE_BASE_URL=f'http://127.0.0.1:{self.ports["FoodMaterialsService"]}',
                      FOOD_MATERIAL_FLYWAY_BASELINE_ON_MIGRATE='false',
                      FOOD_MATERIAL_INVENTORY_FLYWAY_BASELINE_ON_MIGRATE='false', JPA_DDL_AUTO='validate')
        for prefix, schema in [('FOOD_MATERIAL','itemdb'), ('FOOD_MATERIAL_INVENTORY','inventorydb'), ('MENUS','menusdb'), ('DISPOSALS','disposalsdb')]:
            common[prefix+'_DB_URL'] = f'jdbc:mariadb://127.0.0.1:{self.db_port}/{schema}'
            common[prefix+'_DB_USERNAME'] = 'account'
            common[prefix+'_DB_PASSWORD'] = self.password
        for module in MODULES:
            log_path = self.temporary/(module+'.log')
            log = log_path.open('w')
            self.logs.append((log, log_path))
            process = subprocess.Popen([self.java, '-Xmx384m', '-Derpmsa.verification.run='+self.run_id,
                '-Djava.io.tmpdir='+str(self.application_dir), '-jar', self.manifest['jars'][module]['path'],
                '--server.address=127.0.0.1', '--server.port='+str(self.ports[module])],
                cwd=self.application_dir, env=common, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            self.processes.append(process)
            self.apps[module] = process
        self.manifest['ports'] = self.ports
        for module in MODULES:
            deadline = time.monotonic()+90
            while time.monotonic() < deadline:
                if any(p.poll() is not None for p in self.processes[-3:]):
                    raise RuntimeError('Service exited before readiness')
                try:
                    if not self.owns_listener(module):
                        time.sleep(1)
                        continue
                    status, body = self.http(module, '/actuator/health', token=None)
                    if status == 200 and body.get('status') == 'UP':
                        break
                except (OSError, urllib.error.URLError):
                    pass
                time.sleep(1)
            else:
                raise RuntimeError(module+' readiness timeout')
        self.manifest['listeners'] = {module: dict(pid=process.pid, port=self.ports[module], address='127.0.0.1') for module, process in self.apps.items()}
        self.save()

    def owns_listener(self, module):
        process = self.apps[module]
        if process.poll() is not None:
            return False
        result = subprocess.run([self.lsof, '-nP', '-a', '-p', str(process.pid),
            '-iTCP:'+str(self.ports[module]), '-sTCP:LISTEN', '-Fpn'], env=self.env, capture_output=True, text=True, timeout=5)
        lines = result.stdout.splitlines()
        return result.returncode == 0 and 'p'+str(process.pid) in lines and 'n127.0.0.1:'+str(self.ports[module]) in lines

    def token(self, account=101, changes=None, kid=None, wrong_key=False):
        def encode(value):
            return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).rstrip(b'=')
        now = int(time.time())
        claims = dict(iss='g2-fixture', aud='g2-fixture', sub=str(account), iat=now-120, exp=now+1800,
                      token_type='access', email='fixture@example.invalid', role='ROLE_USER')
        claims.update(changes or {})
        data = encode(dict(alg='RS256', typ='JWT', kid=kid or self.kid))+b'.'+encode(claims)
        key = self.credentials/('untrusted/private/wrong.pem' if wrong_key else 'keys/private/'+self.kid+'.pem')
        signature = subprocess.run(['openssl','dgst','-sha256','-sign',str(key)], input=data, capture_output=True, check=True).stdout
        return (data+b'.'+base64.urlsafe_b64encode(signature).rstrip(b'=')).decode()

    def http(self, module, path, method='GET', body=None, account=101, token='default'):
        if not self.owns_listener(module):
            raise RuntimeError('Refusing HTTP: listener not owned by live '+module+' JVM')
        headers = {'Content-Type': 'application/json'}
        if token == 'default':
            token = self.tokens[account]
        if token:
            headers['Authorization'] = 'Bearer '+token
        request = urllib.request.Request(f'http://127.0.0.1:{self.ports[module]}'+path, method=method,
                                         headers=headers, data=None if body is None else json.dumps(body).encode())
        barrier = getattr(self.concurrent_context, 'barrier', None)
        if barrier is not None:
            # Ownership checks can take different amounts of time; align actual HTTP attempts afterwards.
            barrier.wait(timeout=10)
        started = time.monotonic()
        record = dict(scenario=self.scenario, module=module, method=method, path=path, account=account, request=body,
                      startedAtNs=time.time_ns())
        try:
            try:
                response = urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=15)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                raw = response.read()
                result = response_body(response.status, raw, record)
            return record['status'], result
        except Exception as exc:
            record['error'] = type(exc).__name__
            raise
        finally:
            record['seconds'] = round(time.monotonic()-started, 4)
            record['finishedAtNs'] = time.time_ns()
            with self.http_lock, (self.artifact/'http.jsonl').open('a') as log:
                log.write(self.clean_text(json.dumps(record, ensure_ascii=False))+'\n')

    def sql(self, statement):
        self.inspect_owned()
        raw = self.docker('exec', '-i', self.container, 'sh', '-ec',
            'MYSQL_PWD="$ERPMSA_VERIFY_PASSWORD" exec mariadb -uverifier --batch --raw --skip-column-names', input=read_only_sql(statement))
        return [json.loads(line) for line in raw.splitlines() if line]

    def rows(self, table):
        schema = TABLES[table]
        columns = self.sql(f"SELECT JSON_OBJECT('name',COLUMN_NAME) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='{schema}' AND TABLE_NAME='{table}' ORDER BY ORDINAL_POSITION")
        pairs = ','.join("'"+v['name']+"',`"+v['name']+'`' for v in columns)
        if not pairs:
            raise RuntimeError('Missing table '+table)
        return self.sql(f'SELECT JSON_OBJECT({pairs}) FROM {schema}.{table} ORDER BY id')

    def snapshot(self):
        return {table: self.rows(table) for table in TABLES}

    def finish(self):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        errors = []
        for process in self.processes:
            try:
                g1.stop_process(process)
            except Exception as exc:
                errors.append('process: '+type(exc).__name__)
        try:
            leaks = g1.stop_marked_processes(self.run_id)
        except Exception as exc:
            leaks = ['UNVERIFIED']
            errors.append('process inspection: '+type(exc).__name__)
        self.manifest['processLeak'] = leaks
        for log, path in self.logs:
            try:
                log.close()
                (self.artifact/path.name).write_text(self.clean_text(path.read_text(errors='replace')))
            except Exception as exc:
                errors.append('log collection: '+type(exc).__name__)
        removed = []
        if self.container and self.docker_command:
            try:
                owned = self.docker('ps', '-aq', '--no-trunc', '--filter', 'label='+g1.LABEL+'='+self.run_id).split()
                for identifier in owned:
                    item = json.loads(self.docker('inspect', identifier))[0]
                    validate_database(item, self.run_id, self.before)
                    (self.artifact/'database.log').write_text(self.clean_text(self.docker('logs', identifier)))
                    self.docker('rm', '-f', identifier)
                    removed.append(identifier)
                remaining = self.docker('ps', '-aq', '--filter', 'label='+g1.LABEL+'='+self.run_id).split()
            except Exception as exc:
                errors.append('database cleanup: '+type(exc).__name__)
                remaining = ['UNVERIFIED']
        else:
            remaining = []
        self.manifest['cleanup'] = dict(removed=removed, remaining=remaining, errors=errors, passed=not errors and not remaining and not leaks)
        try:
            if self.manifest.get('sourceHashes') != g1.source_hashes(self.env):
                errors.append('source changed during run')
            for evidence in self.manifest['jars'].values():
                if hashlib.sha256(Path(evidence['path']).read_bytes()).hexdigest() != evidence['sha256']:
                    errors.append('JAR changed during run')
            if not leaks:
                shutil.rmtree(self.temporary)
                shutil.rmtree(self.credentials)
            else:
                self.manifest['retainedTemporaryDirectory'] = str(self.temporary)
                self.manifest['retainedCredentialDirectory'] = str(self.credentials)
        except Exception as exc:
            errors.append('finalization: '+type(exc).__name__)
        if errors or remaining or leaks:
            self.manifest['status'] = 'BLOCKED'
            self.manifest['cleanup']['passed'] = False
        self.manifest['finishedAt'] = g1.now()
        self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    (ROOT/'.verification').mkdir(exist_ok=True)
    with (ROOT/'.verification/g1.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run = Run(args.offline)
        print('G2 artifacts: '+str(run.artifact), flush=True)
        try:
            run.preflight()
            run.build()
            run.database()
            run.start_apps()
            from g2_scenarios import execute
            execute(run)
            run.manifest['status'] = aggregate_status(run.manifest['scenarios'])
        except (Failure, AssertionError) as exc:
            run.manifest.update(status='FAIL', error=run.clean_text(str(exc)))
        except (Exception, KeyboardInterrupt) as exc:
            run.manifest.update(status='BLOCKED', error=run.clean_text(type(exc).__name__+': '+str(exc)))
        finally:
            run.finish()
        print(run.manifest['status']+': '+str(run.artifact/'manifest.json'), flush=True)
        return {'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[run.manifest['status']]


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    raise SystemExit(main())
