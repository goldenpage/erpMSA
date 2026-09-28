import importlib.util
from pathlib import Path
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
import tempfile
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('g2', Path(__file__).with_name('run-g2-verification.py'))
g2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g2)
case_spec = importlib.util.spec_from_file_location('cases', Path(__file__).with_name('g2_scenarios.py'))
cases = importlib.util.module_from_spec(case_spec)
case_spec.loader.exec_module(cases)


class G2IsolationTest(unittest.TestCase):
    def database(self):
        return {'Id': 'ours', 'Config': {'Image': 'mariadb:10.11', 'Labels': {
            g2.g1.LABEL: 'run', 'erpmsa.verification.stage': 'G2'}},
            'HostConfig': {'Tmpfs': {'/var/lib/mysql': 'rw'}}, 'Mounts': [],
            'NetworkSettings': {'Ports': {'3306/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '45678'}]}}}

    def test_existing_id_or_foreign_run_is_refused(self):
        with self.assertRaises(RuntimeError):
            g2.validate_database(self.database(), 'run', {'ours'})
        with self.assertRaises(RuntimeError):
            g2.validate_database(self.database(), 'other', set())

    def test_external_port_and_persistent_storage_are_refused(self):
        external = self.database()
        external['NetworkSettings']['Ports']['3306/tcp'][0]['HostIp'] = '0.0.0.0'
        persistent = self.database()
        persistent['Mounts'] = [{'Type': 'volume'}]
        missing = self.database()
        missing['HostConfig']['Tmpfs'] = {}
        for item in (external, persistent, missing):
            with self.assertRaises(RuntimeError):
                g2.validate_database(item, 'run', set())

    def test_only_owned_loopback_tmpfs_database_is_accepted(self):
        self.assertEqual(45678, g2.validate_database(self.database(), 'run', set()))

    def test_business_database_queries_are_read_only(self):
        for sql in ('DELETE FROM disposal', 'UPDATE inventory SET on_hand_quantity=1', 'SELECT 1; DELETE FROM item', 'SELECT 1\n', 'SELECT 1\\g'):
            with self.assertRaises(ValueError):
                g2.read_only_sql(sql)
        self.assertEqual('START TRANSACTION READ ONLY;\nSELECT 1;\nROLLBACK;\n', g2.read_only_sql('SELECT 1'))

    def test_non_json_response_keeps_status_and_body_and_fails(self):
        record = {}
        with self.assertRaises(AssertionError):
            g2.response_body(500, b'<html>server error</html>', record)
        self.assertEqual(500, record['status'])
        self.assertIn('server error', record['rawResponse'])

    def test_incomplete_or_failed_scenarios_never_aggregate_to_pass(self):
        for states, expected in [([], 'BLOCKED'), (['PASS','NOT_RUN'],'BLOCKED'), (['PASS','FAIL'],'FAIL'), (['PASS','PASS'],'PASS')]:
            self.assertEqual(expected, g2.aggregate_status([{'status': s} for s in states]))

    def fake_run(self, folder):
        return SimpleNamespace(manifest={}, artifact=Path(folder), sql=Mock(return_value=[{'success': 1}]),
                               save=Mock(), snapshot=Mock(return_value={}), clean_text=str)

    def execute_with_failure(self, case, exception):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            run = self.fake_run(folder)
            for name in cases.CASES:
                stack.enter_context(patch.object(cases.Cases, 'nf'+name[-2:], side_effect=exception if name == case else None))
            try:
                with patch('builtins.print'):
                    cases.execute(run)
            except BaseException as exc:
                return run.manifest, exc
            return run.manifest, None

    def test_independent_case_continues_but_dependent_case_is_not_run(self):
        manifest, error = self.execute_with_failure('NF-04', AssertionError('menu failure'))
        self.assertIsNone(error)
        states = {e['id']:e['status'] for e in manifest['scenarios']}
        self.assertEqual('FAIL', states['NF-04'])
        self.assertEqual('NOT_RUN', states['NF-07'])
        self.assertEqual('PASS', states['NF-11'])
        self.assertEqual('FAIL', g2.aggregate_status(manifest['scenarios']))

    def test_authentication_failure_stops_business_writes(self):
        manifest, error = self.execute_with_failure('NF-02', AssertionError('auth failure'))
        self.assertIsInstance(error, AssertionError)
        self.assertEqual('FAIL', manifest['scenarios'][0]['status'])
        self.assertTrue(all(e['status'] == 'NOT_RUN' for e in manifest['scenarios'][1:]))

    def test_invalid_write_mutation_is_fail_and_stops_diagnostics(self):
        manifest, error = self.execute_with_failure('NF-08', cases.FatalFailure('DB changed'))
        self.assertIsInstance(error, cases.FatalFailure)
        states = {e['id']:e['status'] for e in manifest['scenarios']}
        self.assertEqual('FAIL', states['NF-08'])
        self.assertEqual('NOT_RUN', states['NF-09'])


if __name__ == '__main__':
    unittest.main()
