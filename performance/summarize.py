#!/usr/bin/env python3
"""Export only allowlisted measurements; never export tokens, env or raw logs."""
import argparse
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'performance/results'

def read(name):
    return json.loads((RESULTS / (name + '.json')).read_text())

def main():
    global RESULTS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results-dir', type=Path, default=RESULTS)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    RESULTS = args.results_dir
    output = {'dataset': read('dataset'), 'http': {}, 'sql': {}, 'faults': {}}
    for label in ['baseline-v2-gateway', 'baseline-v2-direct', 'indexed-gateway', 'indexed-direct', 'final-one', 'final-two']:
        data, conditions = read(label), read(label + '-conditions')
        metrics = data['metrics']
        output['http'][label] = {
            'conditions': {key: conditions[key] for key in ['rate','duration','profile','exitCode','at','preAllocatedVUs','maxVUs','workloadSha256','datasetSha256']},
            'durationMs': metrics['http_req_duration']['values'],
            'requests': metrics['http_reqs']['values'],
            'failureRate': metrics['http_req_failed']['values']['rate'],
            'checkRate': metrics['checks']['values']['rate'],
            'droppedIterations': metrics.get('dropped_iterations', {}).get('values', {}).get('count', 0),
        }
    for label in ['baseline','indexed']:
        output['sql'][label] = []
        for row in read(label + '-sql'):
            sample = row['samples'][0]['query_block']
            table = sample['nested_loop'][0]['table']
            output['sql'][label].append({
                'status': row['status'], 'page': row['page'], 'kind': row['kind'], 'samples': len(row['samples']),
                'medianMs': statistics.median(s['query_block']['r_total_time_ms'] for s in row['samples']),
                'firstSample': {key: table.get(key) for key in ['key','r_rows','r_engine_stats']},
            })
    for name in ['eureka-server-outage-probes','kafka-outage-probes','kafka-recovery','smoke']:
        output['faults'][name] = read(name)
    killed = read('item-kill')
    output['faults']['item-kill'] = {
        'statuses': killed['statuses'], 'durationSeconds': killed['durationSeconds'],
        'injectedSignal': killed['injectedSignal'],
        'state': {key: killed['state'][key] for key in ['Status','Running','OOMKilled','ExitCode']},
    }
    if (RESULTS / 'after-eureka-item-kill.json').exists():
        combined = read('after-eureka-item-kill')
        output['faults']['item-kill-during-eureka-recovery'] = {
            'statuses': combined['statuses'], 'durationSeconds': combined['durationSeconds'],
            'confounded': True,
        }
    replicas = read('final-two-after-metrics')['queries']['rps']['data']['result']
    output['serviceReplicaRps'] = [float(r['value'][1]) for r in replicas if r['metric'].get('job') in ['item-service', 'foodmaterials-service']]
    assert len({v['conditions']['workloadSha256'] for v in output['http'].values()}) == 1, 'Do not mix different workloads'
    assert len({v['conditions']['datasetSha256'] for v in output['http'].values()}) == 1, 'Do not mix different datasets'
    destination = args.output or RESULTS / 'summary.json'
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print('Exported token-free measurements to', destination)

if __name__ == '__main__': main()
