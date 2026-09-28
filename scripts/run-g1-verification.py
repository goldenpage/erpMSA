#!/usr/bin/env python3
"""Run all nine Gradle suites with disposable, labelled Testcontainers (G1 only)."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
MODULES = ('eurekaServer', 'gatewayServer', 'AccountService', 'FoodMaterialsService',
           'MenusService', 'NoticesService', 'BillsService', 'PurchaseService', 'DisposalsService')
LABEL = 'erpmsa.verification.run'
MIN_CONTAINERS = {'AccountService': {'mariadb:': 1, 'redis:': 1, 'apache/kafka:': 1},
                  'FoodMaterialsService': {'mariadb:': 2},
                  'MenusService': {'mariadb:': 1}, 'DisposalsService': {'mariadb:': 1}}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sanitized_environment(source):
    # Do not inherit application .env, JVM options, Spring/DB/JWT or Testcontainers overrides.
    return {k: source[k] for k in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR') if k in source}


def redact(value):
    value = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----', '[REDACTED KEY]', value)
    value = re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[REDACTED JWT]', value)
    value = re.sub(r'(?im)((?:authorization|set-cookie|cookie)\s*[:=]\s*)[^\r\n<]*', r'\1[REDACTED]', value)
    return re.sub(r'(?i)((?:password|refreshToken|accessToken)\s*[=:]\s*)[^\s,;<>]+', r'\1[REDACTED]', value)


def save_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def output(command, env, timeout=30):
    return subprocess.check_output(command, cwd=ROOT, env=env, text=True, stderr=subprocess.PIPE, timeout=timeout).strip()


def source_hashes(env):
    names = output(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], env).splitlines()
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sorted(set(names))
            if (ROOT/name).is_file() and not name.startswith('docs/')}


def evaluate_containers(module, observed, issues):
    missing = [prefix for prefix, count in MIN_CONTAINERS.get(module, {}).items()
               if sum(item['image'].startswith(prefix) for item in observed) < count]
    return dict(passed=not missing and not issues, missingImages=missing, issues=list(issues), containers=observed)


def module_status(code, collected, containers, timed_out):
    if not containers['passed']:
        return 'BLOCKED'
    if code == 0 and collected['passed'] and not timed_out:
        return 'PASS'
    return 'FAIL' if collected['counts']['tests'] else 'BLOCKED'


def marked_processes(run_id):
    marker = re.compile(r'(?:^|\s)-Derpmsa\.verification\.run=' + re.escape(run_id) + r'(?:\s|$)')
    result = {}
    for row in subprocess.check_output(['ps', '-ww', '-axo', 'pid=,lstart=,command='], text=True).splitlines():
        parts = row.split(None, 6)
        if len(parts) == 7 and marker.search(parts[6]):
            result[int(parts[0])] = ' '.join(parts[1:6])
    return result


def stop_marked_processes(run_id):
    # Both the single-use Gradle daemon and all test workers get an explicit JVM marker.
    # Verify process creation time on each signal; never kill unrelated Java processes.
    for sig, wait in ((None, 2), (signal.SIGTERM, 5), (signal.SIGKILL, 3)):
        snapshot = marked_processes(run_id)
        for pid, started in snapshot.items():
            if sig and marked_processes(run_id).get(pid) == started:
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if not marked_processes(run_id):
                return []
            time.sleep(0.2)
    return sorted(marked_processes(run_id))


def expected_classes(module):
    result = set()
    for source in (ROOT / module / 'src/test/java').rglob('*.java'):
        text = source.read_text()
        if re.search(r'@(?:org\.junit\.jupiter\.api\.)?(?:Test|ParameterizedTest|RepeatedTest|TestFactory|TestTemplate)\b', text):
            package = re.search(r'\bpackage\s+([\w.]+)\s*;', text)
            if package:
                result.add(package[1] + '.' + source.stem)
    return result


def collect_xml(folder, destination, started, expected):
    counts = dict(tests=0, failures=0, errors=0, skipped=0)
    classes = set()
    issues = []
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(folder.glob('TEST-*.xml')):
        if path.stat().st_mtime < started:
            issues.append('stale XML: ' + path.name)
            continue
        text = path.read_text()
        try:
            tree = ET.fromstring(text)
            cases = tree.findall('.//testcase')
            if int(tree.get('tests', '-1')) != len(cases):
                issues.append('test count mismatch: ' + path.name)
            for key in counts:
                counts[key] += int(tree.get(key, '0'))
            classes.update(case.get('classname') for case in cases)
            # Independently detect failure/skips even if a report has incorrect summary attributes.
            if any(case.find(tag) is not None for case in cases for tag in ('failure', 'error', 'skipped')):
                issues.append('failed or skipped testcase: ' + path.name)
        except (ET.ParseError, ValueError):
            issues.append('invalid XML: ' + path.name)
        target = destination / path.name
        target.write_text(redact(text))
        target.chmod(0o600)
    missing = sorted(expected - classes)
    if missing:
        issues.append('missing classes: ' + ', '.join(missing))
    if counts['tests'] == 0:
        issues.append('no executed tests')
    passed = not issues and not any(counts[k] for k in ('failures', 'errors', 'skipped'))
    return dict(counts=counts, classes=sorted(c for c in classes if c), issues=issues, passed=passed)


def validate_container(item, run_id, preexisting):
    labels = item['Config'].get('Labels') or {}
    if item['Id'] in preexisting or labels.get(LABEL) != run_id or labels.get('org.testcontainers') != 'true':
        raise RuntimeError('Refusing foreign container: ' + item['Id'])
    image = item['Config']['Image']
    required = next((path for prefix, path in (
        ('mariadb:', '/var/lib/mysql'), ('redis:', '/data'), ('apache/kafka:', '/tmp/kraft-combined-logs')
    ) if image.startswith(prefix)), None)
    if required is None or required not in (item['HostConfig'].get('Tmpfs') or {}):
        raise RuntimeError('Missing disposable storage: ' + item['Id'])
    if any(m.get('Type') in ('bind', 'volume') for m in item.get('Mounts', [])):
        raise RuntimeError('Persistent or host mount in verification container: ' + item['Id'])
    return dict(id=item['Id'], image=image, tmpfs=required)


class DockerResources:
    def __init__(self, endpoint, env, run_id):
        self.command = ['docker', '--host', endpoint]
        self.env = env
        self.run_id = run_id
        self.started_ns = time.time_ns()
        self.before = set(self.call('ps', '-aq', '--no-trunc').split())
        self.observed = {}
        self.helpers = {}
        self.issues = []
        self.module = None
        self.stopping = False
        self.lock = threading.RLock()
        if self.ids():
            raise RuntimeError('Run label already in use')
        self.events = subprocess.Popen([*self.command, 'events', '--since', str(self.started_ns // 1_000_000_000),
            '--filter', 'type=container', '--filter', 'event=create', '--format', '{{json .}}'],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.thread = threading.Thread(target=self.read_events, daemon=True)
        self.thread.start()

    def call(self, *arguments):
        return output([*self.command, *arguments], self.env)

    def ids(self):
        return self.call('ps', '-aq', '--no-trunc', '--filter', f'label={LABEL}={self.run_id}').split()

    def inspect(self, identifier):
        try:
            return json.loads(self.call('inspect', identifier))[0]
        except subprocess.CalledProcessError:
            if identifier not in self.ids():
                return None  # A completed Testcontainers resource may disappear between list and inspect.
            raise

    def record(self, item):
        with self.lock:
            identifier = item['Id']
            if identifier in self.before:
                return
            labels = item['Config'].get('Labels') or {}
            image = item['Config']['Image']
            if image.startswith('testcontainers/ryuk:'):
                # Testcontainers 2.0.5 puts the session UUID in Ryuk's name, not its labels.
                helper_name = item.get('Name', '').removeprefix('/testcontainers-ryuk-')
                session = labels.get('org.testcontainers.sessionId')
                if not session and re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', helper_name):
                    session = helper_name
                self.helpers[identifier] = session
                return
            if labels.get(LABEL) != self.run_id:
                issue = 'unowned new container: ' + identifier
                if issue not in self.issues:
                    self.issues.append(issue)
                return
            validated = validate_container(item, self.run_id, self.before)
            validated.update(module=self.module, sessionId=labels.get('org.testcontainers.sessionId'))
            self.observed.setdefault(identifier, validated)

    def read_events(self):
        try:
            for line in self.events.stdout:
                event = json.loads(line)
                if event.get('timeNano', 0) < self.started_ns:
                    continue
                identifier = event['Actor']['ID']
                if identifier in self.before:
                    continue
                item = self.inspect(identifier)
                if item is None:
                    with self.lock:
                        self.issues.append('unverified create event: ' + identifier)
                else:
                    self.record(item)
        except Exception as exc:
            with self.lock:
                self.issues.append('event inspection failed: ' + str(exc))
        finally:
            if not self.stopping:
                with self.lock:
                    self.issues.append('container event stream ended')

    def audit(self):
        for identifier in set(self.call('ps', '-aq', '--no-trunc').split()) - self.before:
            item = self.inspect(identifier)
            if item:
                self.record(item)
        with self.lock:
            if self.issues or self.events.poll() is not None:
                raise RuntimeError('; '.join(self.issues) or 'Docker event stream unavailable')

    def module_evidence(self, module):
        with self.lock:
            return evaluate_containers(module, [dict(v) for v in self.observed.values() if v['module'] == module], self.issues)

    def close_events(self):
        self.stopping = True
        self.events.terminate()
        try:
            self.events.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.events.kill()
            self.events.wait(timeout=5)
        self.thread.join(timeout=35)

    def cleanup(self):
        removed, errors = [], []
        for identifier in self.ids():
            try:
                item = self.inspect(identifier)
                if item is None:
                    continue
                # Labels + pre-run inventory must both establish ownership before any deletion.
                labels = item['Config'].get('Labels') or {}
                if identifier in self.before or labels.get(LABEL) != self.run_id or labels.get('org.testcontainers') != 'true':
                    raise RuntimeError('Ownership check failed')
                self.call('rm', '-f', identifier)
                removed.append(identifier)
            except Exception as exc:
                # Ryuk may remove the same owned resource between inspect and rm.
                if identifier in self.ids():
                    errors.append(identifier + ': ' + type(exc).__name__)
        remaining = self.ids()
        return dict(removed=removed, remaining=remaining, errors=errors, passed=not remaining and not errors)

    def cleanup_helpers(self):
        removed, errors = [], []
        with self.lock:
            sessions = {v['sessionId'] for v in self.observed.values() if v.get('sessionId')}
            helpers = list(self.helpers.items())
        for identifier, session in helpers:
            if session not in sessions or identifier in self.before:
                continue
            try:
                item = self.inspect(identifier)
                labels = (item['Config'].get('Labels') or {}) if item else {}
                same_session = labels.get('org.testcontainers.sessionId') == session or (item and item.get('Name') == '/testcontainers-ryuk-' + session)
                if item and item['Config']['Image'].startswith('testcontainers/ryuk:') and labels.get('org.testcontainers.ryuk') == 'true' and same_session:
                    self.call('rm', '-f', identifier)
                    removed.append(identifier)
            except Exception as exc:
                if self.inspect(identifier) is not None:
                    errors.append(identifier + ': ' + type(exc).__name__)
        remaining = [identifier for identifier, _ in helpers if self.inspect(identifier)]
        return dict(removed=removed, remaining=remaining, errors=errors, passed=not remaining and not errors)


def stop_process(process):
    if process is None or process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='Require cached Gradle dependencies (Docker images may still be pulled).')
    parser.add_argument('--module-timeout', type=int, default=900)
    args = parser.parse_args()
    if args.module_timeout < 1:
        parser.error('module timeout must be at least 1 second')
    os.umask(0o077)
    runs = ROOT / '.verification'
    runs.mkdir(exist_ok=True)
    lock = (runs / 'g1.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Another G1 run owns this worktree')
    run_id = secrets.token_hex(6)
    artifact = runs / run_id
    artifact.mkdir(mode=0o700)
    report = artifact / 'manifest.json'
    env = sanitized_environment(os.environ)
    temporary = Path(tempfile.mkdtemp(prefix='erpmsa-g1-', dir='/private/tmp' if Path('/private/tmp').exists() else None))
    docker = process = None
    interrupted = False
    manifest = dict(runId=run_id, scope='G1 only; no G2/G3/G4 or remote CI', startedAt=now(), status='RUNNING',
                    modules=[dict(module=m, status='NOT_RUN') for m in MODULES])
    save_json(report, manifest)
    print('G1 artifacts: ' + str(artifact), flush=True)
    try:
        manifest['commit'] = output(['git', 'rev-parse', 'HEAD'], env)
        manifest['changes'] = output(['git', 'status', '--short'], env).splitlines()
        manifest['sourceHashes'] = source_hashes(env)
        gradle_home = Path(env['HOME']) / '.gradle'
        overrides = [p for p in [gradle_home/'gradle.properties', gradle_home/'init.gradle', gradle_home/'init.gradle.kts'] if p.exists()]
        overrides += [p for p in (gradle_home/'init.d').glob('*') if p.is_file()]
        manifest['gradleUserOverrides'] = [str(p) for p in overrides]
        if overrides:
            raise RuntimeError('Gradle user configuration may override isolation; refusing to run')
        manifest['context'] = output(['docker', 'context', 'show'], env)
        context = json.loads(output(['docker', 'context', 'inspect', manifest['context']], env))[0]
        endpoint = context['Endpoints']['docker']['Host']
        if not endpoint.startswith('unix:///') or not stat.S_ISSOCK(Path(endpoint[7:]).stat().st_mode):
            raise RuntimeError('A local Unix Docker socket is required')
        manifest['dockerVersion'] = output(['docker', '--host', endpoint, 'version', '--format', '{{.Server.Version}}'], env)
        docker = DockerResources(endpoint, env, run_id)
        manifest['preexistingContainerIds'] = sorted(docker.before)
        java_home = (output(['/usr/libexec/java_home', '-v', '21'], env) if Path('/usr/libexec/java_home').exists()
                     else str(Path(shutil.which('java', path=env.get('PATH'))).resolve().parent.parent))
        java_version = subprocess.run([java_home + '/bin/java', '-version'], env=env, capture_output=True, text=True, check=True).stderr
        if not re.search(r'version "21(?:\.|\")', java_version):
            raise RuntimeError('Java 21 is required')
        manifest['javaVersion'] = java_version.splitlines()[0]
        home = temporary / 'home'
        home.mkdir()
        init = temporary / 'g1.gradle'
        init.write_text("""allprojects {
    tasks.withType(Test).configureEach {
        systemProperty 'java.io.tmpdir', System.getenv('ERPMSA_VERIFICATION_TMP')
        systemProperty 'user.home', System.getenv('ERPMSA_VERIFICATION_HOME')
        systemProperty 'erpmsa.verification.run', System.getenv('ERPMSA_VERIFICATION_RUN_ID')
    }
}
""")
        env.update(JAVA_HOME=java_home, DOCKER_HOST=endpoint, TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE='/var/run/docker.sock',
                   TESTCONTAINERS_RYUK_DISABLED='false', TESTCONTAINERS_REUSE_ENABLE='false',
                   ERPMSA_VERIFICATION_RUN_ID=run_id, ERPMSA_VERIFICATION_TMP=str(temporary),
                   ERPMSA_VERIFICATION_HOME=str(home),
                   COOKIE_SECURE='false')
        manifest['g0'] = []
        for flag in ([], ['--ci'], ['--performance']):
            result = output(['python3', str(ROOT / 'scripts/verify-service-architecture.py'), *flag], env)
            manifest['g0'].append(dict(mode=flag or ['default'], result=result))
        save_json(report, manifest)
        for module_result in manifest['modules']:
            module = module_result['module']
            expected = expected_classes(module)
            if not expected:
                raise RuntimeError('No expected test classes for ' + module)
            module_result.update(status='RUNNING', startedAt=now(), expectedClasses=sorted(expected))
            save_json(report, manifest)
            print('RUN ' + module, flush=True)
            docker.module = module
            started = time.time()
            deadline = time.monotonic() + args.module_timeout
            command = ['sh', str(ROOT / module / 'gradlew'), '-p', str(ROOT / module), '--init-script', str(init),
                       '-Dorg.gradle.jvmargs=-Xmx512m -XX:MaxMetaspaceSize=384m -Derpmsa.verification.run=' + run_id,
                       'test', '--no-daemon', '--rerun-tasks', '--no-build-cache', '--console=plain']
            if args.offline:
                command.append('--offline')
            module_result['command'] = [x.replace(str(temporary), '<temporary>') for x in command]
            raw_log = temporary / (module + '.log')
            timed_out = False
            module_env = dict(env)
            if module != 'eurekaServer':
                # Eureka Server itself needs its client-side ApplicationInfoManager bean.
                module_env.update(EUREKA_CLIENT_ENABLED='false', SPRING_CLOUD_DISCOVERY_ENABLED='false')
            try:
                with raw_log.open('w') as log:
                    process = subprocess.Popen(command, cwd=ROOT, env=module_env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                    while process.poll() is None:
                        docker.audit()
                        if time.monotonic() > deadline:
                            timed_out = True
                            stop_process(process)
                            break
                        time.sleep(1)
                code = process.returncode
            finally:
                stop_process(process)
                module_result['processLeak'] = stop_marked_processes(run_id)
                if raw_log.exists():
                    (artifact / (module + '.log')).write_text(redact(raw_log.read_text(errors='replace')))
            collected = collect_xml(ROOT / module / 'build/test-results/test', artifact / module, started, expected)
            docker.audit()
            containers = docker.module_evidence(module)
            module_result.update(collected, exitCode=code, finishedAt=now(), seconds=round(time.time() - started, 2), timedOut=timed_out)
            module_result['containerEvidence'] = containers
            module_result['status'] = module_status(code, collected, containers, timed_out)
            if module_result['processLeak']:
                module_result['status'] = 'BLOCKED'
            print(module_result['status'] + ' ' + module + ' ' + json.dumps(collected['counts']), flush=True)
            save_json(report, manifest)
            if module_result['status'] != 'PASS':
                break
        manifest['status'] = ('PASS' if all(m['status'] == 'PASS' for m in manifest['modules'])
                              else 'FAIL' if any(m['status'] == 'FAIL' for m in manifest['modules']) else 'BLOCKED')
    except KeyboardInterrupt:
        interrupted = True
        manifest.update(status='BLOCKED', error='Interrupted')
    except Exception as exc:
        manifest.update(status='BLOCKED', error=redact(str(exc)))
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        finalization_errors = []
        try:
            stop_process(process)
        except Exception as exc:
            finalization_errors.append('wrapper termination: ' + type(exc).__name__)
        try:
            manifest['processLeak'] = stop_marked_processes(run_id)
        except Exception as exc:
            manifest['processLeak'] = ['UNVERIFIED']
            finalization_errors.append('JVM termination: ' + type(exc).__name__)
        if manifest['processLeak']:
            manifest['status'] = 'BLOCKED'
        for result in manifest['modules']:
            if result['status'] == 'RUNNING':
                result['status'] = 'BLOCKED'
        if docker:
            try:
                manifest['cleanup'] = docker.cleanup()
                time.sleep(3)
                late = docker.ids()
                manifest['lateContainers'] = late
                if late:
                    manifest['lateCleanup'] = docker.cleanup()
                    manifest['cleanup']['passed'] = False
                manifest['helperCleanup'] = docker.cleanup_helpers()
                if not manifest['helperCleanup']['passed']:
                    manifest['cleanup']['passed'] = False
            except Exception as exc:
                manifest['cleanup'] = dict(passed=False, error=type(exc).__name__)
            finally:
                try:
                    docker.close_events()
                except Exception as exc:
                    finalization_errors.append('event stream shutdown: ' + type(exc).__name__)
                with docker.lock:
                    manifest['containers'] = list(docker.observed.values())
                    manifest['containerIssues'] = list(docker.issues)
            if docker.issues:
                manifest['status'] = 'BLOCKED'
            if not manifest['cleanup']['passed']:
                manifest['status'] = 'BLOCKED'
        else:
            manifest['cleanup'] = dict(passed=True, note='No containers created by this runner')
        if not manifest['processLeak']:
            try:
                shutil.rmtree(temporary)
            except Exception as exc:
                finalization_errors.append('temporary directory cleanup: ' + type(exc).__name__)
                manifest['retainedTemporaryDirectory'] = str(temporary)
        else:
            manifest['retainedTemporaryDirectory'] = str(temporary)
        try:
            if manifest.get('sourceHashes') != source_hashes(env):
                manifest.update(status='BLOCKED', sourceChangedDuringRun=True)
        except Exception as exc:
            finalization_errors.append('final source hash: ' + type(exc).__name__)
        manifest['finalizationErrors'] = finalization_errors
        if finalization_errors:
            manifest['status'] = 'BLOCKED'
        manifest['finishedAt'] = now()
        save_json(report, manifest)
    print(manifest['status'] + ': ' + str(report), flush=True)
    return 130 if interrupted else {'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[manifest['status']]


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    raise SystemExit(main())
