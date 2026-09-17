#!/usr/bin/env python3
"""Check the user-approved service identity contract without starting containers."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--ci', action='store_true')
    mode.add_argument('--performance', action='store_true')
    args = parser.parse_args()
    contract = json.loads((ROOT / 'architecture/services.json').read_text())
    services = contract['services']
    assert len(services) == 7
    assert not contract.get('supportServices'), 'Unapproved support services'
    modules = {s['applicationName'] for s in services}
    actual_modules = {p.name for p in ROOT.glob('*Service') if p.is_dir()}
    assert actual_modules == modules, f'Service folders: {actual_modules ^ modules}'
    expected_runtime = {s['path'][1:] + '-service' for s in services}
    spring_runtime = expected_runtime | {'eureka-server', 'gateway-server'}
    for field in ['applicationName', 'port', 'path']:
        assert len({s[field] for s in services}) == len(services), field
    env = dict(os.environ)
    # Parsing only: placeholders avoid requiring real credentials for this check.
    for key in ['DB_PASSWORD', 'GRAFANA_ADMIN_PASSWORD', 'GRAFANA_SECRET_KEY']:
        env[key] = 'architecture-validation-only'
    command = ['docker', 'compose', '--env-file', str(ROOT / '.env.example'), '-f', str(ROOT / 'compose.yaml')]
    if args.ci: command += ['-f', str(ROOT / 'compose.ci.yaml')]
    if args.performance: command += ['-f', str(ROOT / 'compose.performance.yaml')]
    command += ['config', '--format', 'json']
    config = json.loads(subprocess.check_output(command, cwd=ROOT, env=env, text=True))
    infrastructure = {'mariadb', 'database-init', 'redis', 'kafka', 'prometheus', 'grafana'}
    allowed_services = spring_runtime | infrastructure | ({'k6'} if args.performance else set())
    assert not set(config['services']) - allowed_services, 'Unapproved Compose services'
    built_apps = {name for name, service in config['services'].items()
                  if 'build' in service and name not in {'prometheus', 'grafana'}}
    assert built_apps == spring_runtime, f'Compose application set: {built_apps ^ spring_runtime}'
    for name, runtime in config['services'].items():
        assert set(runtime.get('depends_on', {})) <= set(config['services']), name
    monitoring = (ROOT / 'monitoring/prometheus/prometheus.yml').read_text()
    jobs = set(re.findall(r'job_name:\s*(\S+)', monitoring))
    assert jobs == spring_runtime | {'prometheus'}, 'Prometheus service set'
    dashboard = json.loads((ROOT / 'monitoring/grafana/dashboards/erpmsa-spring-services.json').read_text())
    job_filter = next(v for v in dashboard['templating']['list'] if v['name'] == 'job')['allValue']
    assert set(job_filter.split('|')) == spring_runtime, 'Grafana service set'
    gateway = (ROOT / 'gatewayServer/src/main/resources/application.yml').read_text()
    route_paths = re.findall(r'Path=(/[^\s]+)', gateway)
    assert sorted(route_paths) == sorted(s['path'] + '/**' for s in services), 'Gateway route set'
    targets = re.findall(r'uri: lb://([^\s]+)', gateway)
    assert sorted(t.upper() for t in targets) == sorted(s['applicationName'].upper() for s in services)
    for s in services:
        module, port, path = s['applicationName'], s['port'], s['path']
        runtime = config['services'][path[1:] + '-service']
        application = (ROOT / module / 'src/main/resources/application.yaml').read_text()
        assert re.search(r'name:\s*' + module + r'\s*\n', application), module
        assert re.search(r'port:.*:' + str(port) + r'\}', application), module
        assert runtime['build']['dockerfile'] == module + '/Dockerfile', module
        assert str(port) in [str(v) for k,v in runtime['environment'].items() if k.endswith('_SERVER_PORT')], module
        if args.ci or args.performance:
            assert not runtime.get('ports'), module
        else:
            assert any(p['target'] == port and p['published'] == str(port) and p['host_ip'] == '127.0.0.1' for p in runtime['ports']), module
        assert any(v['target'] == '/run/jwt-public' and v.get('read_only') for v in runtime['volumes']), module
        if module != 'AccountService':
            assert not runtime.get('secrets'), module
            assert not any('private' in v['target'] for v in runtime['volumes']), module
        if s['implementationStatus'] == 'authenticated-shell':
            assert 'base-path: ' + path in application, module
    print('PASS: exactly 7 business modules, Compose applications, ports, Gateway routes, key boundaries and 9 Spring monitoring targets'
          + (' (CI)' if args.ci else ' (performance)' if args.performance else ''))

if __name__ == '__main__': main()
