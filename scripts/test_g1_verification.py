import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import threading
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('g1', Path(__file__).with_name('run-g1-verification.py'))
g1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g1)


class VerificationSafetyTest(unittest.TestCase):
    def test_application_and_jvm_overrides_are_not_inherited(self):
        supplied = dict(PATH='/bin', HOME='/home/test', SPRING_APPLICATION_JSON='production',
                        FOOD_MATERIAL_INVENTORY_DB_URL='production', JAVA_TOOL_OPTIONS='production',
                        DOCKER_HOST='tcp://remote:2375', TESTCONTAINERS_REUSE_ENABLE='true')
        self.assertEqual({'PATH': '/bin', 'HOME': '/home/test'}, g1.sanitized_environment(supplied))

    def container(self):
        return {'Id': 'new', 'Config': {'Image': 'mariadb:10.11', 'Labels': {
            g1.LABEL: 'test-run', 'org.testcontainers': 'true'}},
            'HostConfig': {'Tmpfs': {'/var/lib/mysql': 'rw'}}, 'Mounts': []}

    def test_existing_container_is_never_owned_even_with_matching_label(self):
        with self.assertRaises(RuntimeError):
            g1.validate_container(self.container(), 'test-run', {'new'})

    def test_foreign_label_or_persistent_mount_is_rejected(self):
        foreign = self.container()
        foreign['Config']['Labels'][g1.LABEL] = 'another-run'
        persistent = self.container()
        persistent['Mounts'] = [{'Type': 'volume', 'Name': 'erpmsa-mariadb-data'}]
        for item in (foreign, persistent):
            with self.assertRaises(RuntimeError):
                g1.validate_container(item, 'test-run', set())

    def test_data_directory_must_use_tmpfs(self):
        item = self.container()
        item['HostConfig']['Tmpfs'] = {}
        with self.assertRaises(RuntimeError):
            g1.validate_container(item, 'test-run', set())

    def test_stale_xml_and_missing_suites_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            xml = folder / 'TEST-A.xml'
            xml.write_text('<testsuite tests="1"><testcase classname="A" name="test"/></testsuite>')
            os.utime(xml, (1, 1))
            result = g1.collect_xml(folder, folder/'out', time.time(), {'A', 'B'})
            self.assertFalse(result['passed'])
            self.assertEqual(0, result['counts']['tests'])

    def test_skipped_case_is_failure_even_with_incorrect_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            started = time.time() - 1
            (folder/'TEST-A.xml').write_text('<testsuite tests="1" skipped="0"><testcase classname="A" name="test"><skipped/></testcase></testsuite>')
            self.assertFalse(g1.collect_xml(folder, folder/'out', started, {'A'})['passed'])

    def test_artifacts_redact_bearer_cookies_and_private_keys(self):
        text = 'Authorization: Bearer secret\nCookie: refreshToken=secret\n-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----'
        self.assertNotIn('secret', g1.redact(text))

    def test_container_minimum_and_unverified_observation_block_pass(self):
        self.assertFalse(g1.evaluate_containers('AccountService', [], [])['passed'])
        self.assertFalse(g1.evaluate_containers('FoodMaterialsService', [{'image': 'mariadb:10.11'}], [])['passed'])
        self.assertFalse(g1.evaluate_containers('gatewayServer', [], ['unverified create'])['passed'])

    def resources(self):
        resource = g1.DockerResources.__new__(g1.DockerResources)
        resource.run_id = 'test-run'
        resource.before = set()
        resource.observed, resource.helpers, resource.issues = {}, {}, []
        resource.module = 'AccountService'
        resource.lock = threading.RLock()
        return resource

    def test_foreign_container_is_blocked_but_ryuk_is_classified_separately(self):
        resource = self.resources()
        item = self.container()
        item['Config']['Labels'][g1.LABEL] = 'standalone'
        resource.record(item)
        self.assertFalse(resource.module_evidence('AccountService')['passed'])
        self.assertEqual(['unowned new container: new'], resource.issues)
        helper = self.container()
        helper['Id'] = 'helper'
        helper['Config']['Image'] = 'testcontainers/ryuk:0.14.0'
        resource.record(helper)
        self.assertIn('helper', resource.helpers)
        self.assertEqual(1, len(resource.issues))

    def test_cleanup_never_removes_existing_or_foreign_container(self):
        for existing in (True, False):
            resource = self.resources()
            item = self.container()
            if existing:
                resource.before.add('new')
            else:
                item['Config']['Labels'][g1.LABEL] = 'other'
            resource.ids = Mock(return_value=['new'])
            resource.inspect = Mock(return_value=item)
            resource.call = Mock()
            self.assertFalse(resource.cleanup()['passed'])
            resource.call.assert_not_called()

    def test_failed_exit_or_missing_xml_never_passes(self):
        good = {'passed': True, 'counts': {'tests': 1}}
        containers = {'passed': True}
        self.assertEqual('FAIL', g1.module_status(1, good, containers, False))
        self.assertEqual('FAIL', g1.module_status(0, good, containers, True))
        self.assertEqual('BLOCKED', g1.module_status(1, {'passed': False, 'counts': {'tests': 0}}, containers, False))

    def test_process_marker_requires_exact_run_id(self):
        rows = ('123 Mon Sep 28 11:00:00 2026 java -Derpmsa.verification.run=test-run Worker\n'
                '124 Mon Sep 28 11:00:00 2026 java -Derpmsa.verification.run=test-run-other Worker\n')
        with patch.object(g1.subprocess, 'check_output', return_value=rows):
            self.assertEqual({123: 'Mon Sep 28 11:00:00 2026'}, g1.marked_processes('test-run'))

    def test_reused_pid_is_not_signalled(self):
        snapshots = [{123: 'old'}, {123: 'old'}, {123: 'new'}, {}, {}]
        with patch.object(g1, 'marked_processes', side_effect=snapshots), \
             patch.object(g1.time, 'monotonic', side_effect=[0, 3, 4, 4]), \
             patch.object(g1.os, 'kill') as kill:
            self.assertEqual([], g1.stop_marked_processes('test-run'))
            kill.assert_not_called()

    def test_disappeared_create_and_ended_event_stream_are_recorded(self):
        resource = self.resources()
        resource.started_ns = 1
        resource.stopping = False
        resource.events = Mock(stdout=io.StringIO(json.dumps({'timeNano': 2, 'Actor': {'ID': 'gone'}}) + '\n'))
        resource.inspect = Mock(return_value=None)
        resource.read_events()
        self.assertIn('unverified create event: gone', resource.issues)
        self.assertIn('container event stream ended', resource.issues)

    def test_helper_requires_session_owned_by_verified_container(self):
        resource = self.resources()
        session = '12345678-1234-1234-1234-123456789abc'
        item = self.container()
        item['Config']['Image'] = 'testcontainers/ryuk:0.14.0'
        item['Config']['Labels']['org.testcontainers.ryuk'] = 'true'
        item['Name'] = '/testcontainers-ryuk-' + session
        resource.record(item)
        resource.inspect = Mock(return_value=item)
        resource.call = Mock()
        self.assertFalse(resource.cleanup_helpers()['passed'])
        resource.call.assert_not_called()
        resource.observed['database'] = {'sessionId': session}
        resource.inspect = Mock(side_effect=[item, None])
        self.assertTrue(resource.cleanup_helpers()['passed'])
        resource.call.assert_called_once_with('rm', '-f', 'new')

    def test_helper_wrong_name_or_missing_ryuk_label_is_not_deleted(self):
        for labels, name in (({'org.testcontainers.ryuk': 'true'}, '/different'), ({}, '/testcontainers-ryuk-session')):
            resource = self.resources()
            resource.helpers['helper'] = 'session'
            resource.observed['database'] = {'sessionId': 'session'}
            resource.inspect = Mock(return_value={'Config': {'Image': 'testcontainers/ryuk:0.14.0', 'Labels': labels}, 'Name': name})
            resource.call = Mock()
            self.assertFalse(resource.cleanup_helpers()['passed'])
            resource.call.assert_not_called()

    def test_ryuk_concurrent_removal_preserves_cleanup_evidence(self):
        resource = self.resources()
        resource.helpers['helper'] = 'session'
        resource.observed['database'] = {'sessionId': 'session'}
        item = {'Config': {'Image': 'testcontainers/ryuk:0.14.0', 'Labels': {'org.testcontainers.ryuk': 'true'}},
                'Name': '/testcontainers-ryuk-session'}
        resource.inspect = Mock(side_effect=[item, None, None])
        resource.call = Mock(side_effect=RuntimeError('already removed'))
        result = resource.cleanup_helpers()
        self.assertTrue(result['passed'])
        self.assertEqual([], result['errors'])


if __name__ == '__main__':
    unittest.main()
