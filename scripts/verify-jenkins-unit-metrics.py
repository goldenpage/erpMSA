#!/usr/bin/env python3
"""Replay one Jenkins unit report into the disposable stack and verify its Grafana data."""
import base64
import json
import os
from pathlib import Path
import re
import runpy
import sys
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def main():
    report_dir = Path(sys.argv[1])
    pushgateway = sys.argv[2]
    report = json.loads((report_dir / 'summary.json').read_text())
    run, results = report['run'], report['results']
    run_id = run['id']
    if run['project'] != 'ErpMSA' or run['source'] != 'jenkins' or not re.fullmatch(r'jenkins-\d+', run_id):
        raise ValueError('Expected the ErpMSA Jenkins unit test report')
    publisher = runpy.run_path(str(Path(__file__).with_name('run-spring-tests.py')))
    for result in results:
        if result['suite'] != 'unit':
            raise ValueError('Expected unit results only')
        metrics = (report_dir / 'unit' / result['module'] / 'metrics.prom').read_text()
        publisher['push_metrics'](pushgateway, result, run, metrics)

    credentials = f"{os.environ['GRAFANA_ADMIN_USER']}:{os.environ['GRAFANA_ADMIN_PASSWORD']}"
    headers = {'Authorization': 'Basic ' + base64.b64encode(credentials.encode()).decode()}
    grafana = os.environ.get('GRAFANA_URL', 'http://grafana:3000').rstrip('/')

    def query(path):
        with urlopen(Request(grafana + path, headers=headers), timeout=10) as response:
            return json.load(response)

    for uid in ('erpmsa-spring-unit-tests', 'kosta-personal-verification', 'erpmsa-ocr-benchmark'):
        dashboard = query('/api/dashboards/uid/' + uid)
        if not dashboard['meta']['provisioned'] or dashboard['dashboard']['uid'] != uid:
            raise RuntimeError(f'Grafana dashboard is not provisioned: {uid}')

    labels = 'job="spring_unit_tests",project="ErpMSA",source="jenkins"'
    info = f'erpmsa_unit_test_info{{{labels},run_id="{run_id}"}}'
    total = sum(result['tests']['total'] for result in results)
    queries = {
        f'count({info})': len(results),
        f'sum(erpmsa_unit_test_cases{{{labels},result="total"}} and on (project, source, branch, module) {info})': total,
    }
    deadline = time.monotonic() + 75
    while time.monotonic() < deadline:
        try:
            values = []
            for expression in queries:
                path = '/api/datasources/proxy/uid/prometheus/api/v1/query?'
                response = query(path + urlencode({'query': expression}))
                values.append([float(item['value'][1]) for item in response['data']['result']])
            if values == [[expected] for expected in queries.values()]:
                print(f'Grafana returned {total} Jenkins unit tests across {len(results)} modules.')
                return
        except URLError:
            pass
        time.sleep(5)
    raise RuntimeError(f'Grafana did not return metrics for {run_id}')


if __name__ == '__main__':
    main()
