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
    parser.add_argument('--ci', action='store_true')
    args = parser.parse_args()
    contract = json.loads((ROOT / 'architecture/services.json').read_text())
    services = contract['services']
    assert len(services) == 7
    for field in ['applicationName', 'port', 'path']:
        assert len({s[field] for s in services}) == len(services), field
    env = dict(os.environ)
    # Parsing only: placeholders avoid requiring real credentials for this check.
    for key in ['DB_PASSWORD', 'GRAFANA_ADMIN_PASSWORD', 'GRAFANA_SECRET_KEY']:
        env[key] = 'architecture-validation-only'
    command = ['docker', 'compose', '--env-file', str(ROOT / '.env.example'), '-f', str(ROOT / 'compose.yaml')]
    if args.ci: command += ['-f', str(ROOT / 'compose.ci.yaml')]
    command += ['config', '--format', 'json']
    config = json.loads(subprocess.check_output(command, cwd=ROOT, env=env, text=True))
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
        if args.ci:
            assert not runtime.get('ports'), module
        else:
            assert any(p['target'] == port and p['published'] == str(port) and p['host_ip'] == '127.0.0.1' for p in runtime['ports']), module
        assert any(v['target'] == '/run/jwt-public' and v.get('read_only') for v in runtime['volumes']), module
        if module != 'AccountService':
            assert not runtime.get('secrets'), module
            assert not any('private' in v['target'] for v in runtime['volumes']), module
        if s['implementationStatus'] == 'authenticated-shell':
            assert 'base-path: ' + path in application, module
    for s in contract['supportServices']:
        service = 'audit-service' if s['applicationName']=='AuditService' else 'inventory-service'
        runtime=config['services'][service]
        assert not runtime.get('ports'), service
        assert str(s['port']) in [str(v) for k,v in runtime['environment'].items() if k.endswith('_SERVER_PORT')]
    print('PASS: 7 service modules, ports, Gateway routes, key boundaries and internal support services' + (' (CI)' if args.ci else ''))

if __name__ == '__main__': main()
