import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("kosta_verification", Path(__file__).with_name("run-kosta-personal-verification.py"))
verification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verification)


class PersonalVerificationTest(unittest.TestCase):
    def replay(self):
        return {"run": {"executions": [{"item": {"name": route}, "response": {"code": 200},
                "assertions": [{"assertion": "HTTP 200"}, {"assertion": "fixture"}]} for route in verification.EXPECTED_API]}}

    def test_historical_requests_are_scoped_and_not_counted_as_passes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.log"
            path.write_text('GET /api/statistics/disposals/rate\nGET /api/notices\n')
            result = verification.history_evidence(path)
        self.assertEqual(sum(bool(v) for v in result["routes"].values()), 1)
        self.assertNotIn("/api/notices", result["routes"])
        self.assertIn("historical-response-not-verified", result["status"])

    def test_reconstructed_collection_uses_only_recorded_apis_and_no_token(self):
        collection = verification.collection()
        self.assertEqual({x["name"] for x in collection["item"]}, set(verification.EXPECTED_API))
        self.assertIn("{{accessToken}}", json.dumps(collection))
        self.assertTrue(all(x["request"]["method"] == "GET" for x in collection["item"]))

    def test_failed_and_skipped_assertions_cannot_be_passes(self):
        report = self.replay()
        report["run"]["executions"][0]["assertions"][1]["error"] = {"name": "AssertionError"}
        report["run"]["executions"][1]["assertions"][1]["skipped"] = True
        result = verification.summarize_newman(report)
        self.assertEqual(sum(x["passed"] for x in result), 6)

    def test_missing_or_duplicate_api_execution_is_rejected(self):
        report = self.replay()
        report["run"]["executions"][-1] = copy.deepcopy(report["run"]["executions"][0])
        with self.assertRaisesRegex(ValueError, "8개"):
            verification.summarize_newman(report)

    def test_history_and_db_verification_do_not_change_unit_coverage_metrics(self):
        summary = {"branch": "develop", "revision": "a", "id": "r", "finishedTimestamp": 1,
                   "postmanHistory": {"routes": {r: [1] for r in verification.EXPECTED_API}}, "statistics": {}}
        metrics = verification.metrics(summary)
        self.assertIn("erpmsa_personal_postman_history", metrics)
        self.assertNotIn("erpmsa_personal_postman_passed", metrics)
        self.assertNotIn("erpmsa_unit_test", metrics)

    def test_swagger_scope_excludes_other_controllers(self):
        class Response(io.BytesIO):
            status = 200
        document = {"openapi": "3.0.1", "components": {"securitySchemes": {"bearerAuth": {"scheme": "bearer", "bearerFormat": "JWT"}}},
                    "paths": {"/api/statistics/example": {"get": {"responses": {"200": {}}}},
                              "/api/notices": {"get": {"responses": {"200": {"description": "ignored"}}}},
                              "/api/auth/login": {"post": {"requestBody": {"content": {"application/json": {"schema": {"required": ["username", "password"]}}}},
                                                       "responses": {"200": {"headers": {"Authorization": {}, "Set-Cookie": {}}}}}}}}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            controller = root / verification.REVIEWED_FILES[2]
            controller.parent.mkdir(parents=True)
            controller.write_text('@GetMapping("/example")')
            with patch.object(verification.urllib.request, "urlopen", side_effect=[Response(json.dumps(document).encode()), Response(b'Swagger UI')]):
                result = verification.check_swagger("http://localhost", root)
        self.assertEqual({x["endpoint"] for x in result["routes"]}, {"/api/statistics/example", "/api/auth/login"})
        self.assertFalse(result["passed"])

    def test_member_dao_methods_receive_independent_prerequisites(self):
        cls = verification.PREFIX + "repository.UserinfoDAOTest"
        setup_sql, commands = [], []
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def execute(args, **kwargs):
                selected = next(x for x in args if x.startswith("-Dit.test="))
                method = selected.split("#", 1)[1]
                reports = root / "target/failsafe-reports"
                reports.mkdir(parents=True, exist_ok=True)
                (reports / "TEST-member.xml").write_text(f'<testsuite><testcase classname="{cls}" name="{method}()"/></testsuite>')
                commands.append(selected)
                return type("Result", (), {"returncode": 0})()
            with patch.object(verification, "ACCOUNT_TESTS", {cls: ("member_repository", 7)}), patch.object(verification.subprocess, "run", side_effect=execute):
                result = verification.run_account_tests(root, {}, root / "out", setup_sql.append)
        self.assertEqual(result["member_repository"]["passed"], 7)
        self.assertEqual(len(set(commands)), 7)
        self.assertEqual(sum("'kim123!'" in sql for sql in setup_sql), 1)
        self.assertEqual(sum("'test123'" in sql for sql in setup_sql), 6)
        self.assertTrue(all("DELETE FROM USERINFO" in sql for sql in setup_sql))

    def test_account_results_are_separate_from_statistics_and_unit_coverage(self):
        counts = {"total": 7, "passed": 7, "failed": 0, "errors": 0, "skipped": 0}
        summary = {"branch": "develop", "revision": "a", "id": "r", "finishedTimestamp": 1,
                   "postmanHistory": {"routes": {}}, "accounts": {"account_service": counts}}
        metrics = verification.metrics(summary)
        self.assertIn('kind="account_service",suite="integration",result="passed"} 7.0', metrics)
        self.assertNotIn("statistics_service", metrics)
        self.assertNotIn("erpmsa_unit_test_coverage", metrics)

    def test_skipped_account_case_cannot_produce_successful_verification(self):
        cls = verification.PREFIX + "service.RegistrationReviewServiceTest"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def execute(args, **kwargs):
                reports = root / 'target/failsafe-reports'
                reports.mkdir(parents=True, exist_ok=True)
                (reports / 'TEST-review.xml').write_text(f'<testsuite><testcase classname="{cls}" name="skipped"><skipped/></testcase></testsuite>')
                return type('Result', (), {'returncode': 0})()
            with patch.object(verification, 'ACCOUNT_TESTS', {cls: ('registration_review', 1)}), patch.object(verification.subprocess, 'run', side_effect=execute):
                with self.assertRaisesRegex(ValueError, '건너뜀'):
                    verification.run_account_tests(root, {}, root / 'out', lambda sql: None)

    def test_active_methods_ignore_comments_and_allow_transactional_annotations(self):
        source = '''class A {
            // @Test void commented() {}
            /* @Test void inactive() {} */
            @Test @Transactional void actual() { String value = "}"; }
        }'''
        self.assertEqual([m[0] for m in verification.test_methods(source)], ["actual"])

    def test_service_and_phone_tests_are_excluded_from_db_execution(self):
        database = set(verification.TESTS) | set(verification.ACCOUNT_TESTS)
        self.assertFalse(database & verification.reporting.KOSTA_PERSONAL_UNIT_TESTS)
        self.assertIn(verification.PREFIX + "service.AuthServiceTest", verification.reporting.KOSTA_PERSONAL_UNIT_TESTS)
        self.assertIn(verification.PREFIX + "service.StatisticsServiceTest", verification.reporting.KOSTA_PERSONAL_UNIT_TESTS)
        self.assertIn(verification.PREFIX + "service.PhoneVerificationServiceTest", verification.reporting.KOSTA_PERSONAL_UNIT_TESTS)

    def test_context_smoke_is_not_counted_as_personal_business_test(self):
        summary = {"branch": "develop", "revision": "a", "id": "r", "finishedTimestamp": 1,
                   "postmanHistory": {"routes": {}}, "contextSmoke": {"total": 1, "passed": 1, "failed": 0, "errors": 0, "skipped": 0}}
        payload = verification.metrics(summary)
        self.assertIn('erpmsa_personal_context_smoke_cases', payload)
        self.assertNotIn('erpmsa_personal_verification_cases', payload)

    def inventory_fixture(self, method_author):
        source = ['package example;', 'import example.Dependency;', '@Tag("integration")',
                  'class SharedTest {', ' @Test void actual() {', '  check();', ' }', '}']
        blame = '\n'.join('author ' + ('jong845' if i == 1 else method_author) + '\n\t' + line for i, line in enumerate(source))
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            path = project / 'src/test/java/example/SharedTest.java'
            path.parent.mkdir(parents=True)
            path.write_text('\n'.join(source))
            with patch.object(verification, 'command', return_value=blame), patch.object(verification.reporting, 'classify_tests', return_value={'unit': set(), 'integration': {'example.SharedTest'}}):
                return verification.audit_inventory(project)

    def test_personal_import_edit_does_not_claim_teammate_test(self):
        row = self.inventory_fixture('teammate')[0]
        self.assertEqual(row['personalMethods'], [])
        self.assertFalse(row['selected'])

    def test_new_personal_test_cannot_be_silently_omitted(self):
        with self.assertRaisesRegex(ValueError, '누락'):
            self.inventory_fixture('jong845')


if __name__ == "__main__":
    unittest.main()
