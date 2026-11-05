import importlib.util
import contextlib
import io
from datetime import datetime
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("spring_tests", Path(__file__).with_name("run-spring-tests.py"))
reporting = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporting)


class SpringTestReportingTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.patch = patch.object(reporting, "ROOT", self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temporary.cleanup()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def collect(self, expected=(), code=0):
        return reporting.collect("AccountService", "unit", code, set(expected), self.root / "out", datetime.now().astimezone(), 1.0)

    def test_junit_distinguishes_failure_error_skip_and_duration(self):
        path = self.write("tests.xml", '''<testsuite><testcase classname="A" name="ok" time="0.1"/>
            <testcase classname="A" name="fail" time="0.2"><failure/></testcase>
            <testcase classname="A" name="error" time="0.3"><error/></testcase>
            <testcase classname="A" name="skip"><skipped/></testcase></testsuite>''')
        result = reporting.read_junit([path])
        self.assertEqual([result[k] for k in ("total", "passed", "failed", "errors", "skipped")], [4, 1, 1, 1, 1])
        self.assertAlmostEqual(result["durationSeconds"], 0.6)

    def test_coverage_counts_only_report_totals_and_leaves_zero_denominator_undefined(self):
        path = self.write("jacoco.xml", '''<report><package name="x"><counter type="LINE" missed="2" covered="8"/></package>
            <counter type="LINE" missed="2" covered="8"/><counter type="BRANCH" missed="0" covered="0"/></report>''')
        result = reporting.read_coverage(path)
        self.assertEqual(result["LINE"], {"missed": 2, "covered": 8, "ratio": 0.8})
        self.assertIsNone(result["BRANCH"]["ratio"])

    def test_module_without_unit_tests_is_not_a_perfect_pass(self):
        result = self.collect()
        self.assertEqual(result["state"], "no_tests")
        self.assertIsNone(result["coverage"])
        text = reporting.prometheus_text(result, {"source": "local", "branch": "main", "revision": "a", "dirty": True, "id": "r"})
        self.assertNotIn("erpmsa_unit_test_success_ratio", text)
        self.assertNotIn("erpmsa_unit_test_coverage_ratio", text)

    def test_expected_tests_with_missing_reports_are_build_error(self):
        result = self.collect(["example.AccountTest"])
        self.assertEqual(result["state"], "build_error")
        self.assertIn("누락", result["error"])

    def test_integration_results_cannot_be_reported_as_unit_tests(self):
        self.write("AccountService/build/test-results/test/TEST-Wrong.xml", '<testsuite><testcase classname="example.IntegrationTest" name="x"/></testsuite>')
        result = self.collect(["example.UnitTest"])
        self.assertEqual(result["state"], "build_error")
        self.assertIn("다른 그룹", result["error"])

    def test_build_failure_with_no_reports_is_not_no_tests(self):
        self.assertEqual(self.collect(code=1)["state"], "build_error")

    def test_all_skipped_does_not_produce_coverage(self):
        self.write("AccountService/build/test-results/test/TEST-A.xml", '<testsuite><testcase classname="example.A" name="x"><skipped/></testcase></testsuite>')
        self.write("AccountService/build/reports/jacoco/test/jacocoTestReport.xml", '<report><counter type="LINE" missed="10" covered="0"/></report>')
        result = self.collect(["example.A"])
        self.assertEqual(result["state"], "skipped")
        self.assertIsNone(result["coverage"])

    def test_untagged_tests_are_rejected(self):
        self.write("AccountService/src/test/java/example/A.java", 'package example; class A { @Test void x() {} }')
        with self.assertRaisesRegex(ValueError, "태그"):
            reporting.classify_tests("AccountService")

    def test_context_tests_cannot_be_tagged_as_unit(self):
        self.write("AccountService/src/test/java/example/A.java", 'package example; @Tag("unit") @SpringBootTest class A { @Test void x() {} }')
        with self.assertRaisesRegex(ValueError, "컨텍스트"):
            reporting.classify_tests("AccountService")

    def test_clean_git_status_remains_empty(self):
        with patch.object(reporting.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="")):
            self.assertEqual(reporting.git_value("status", "--porcelain"), "")

    def test_gradle_launcher_failure_replaces_previous_success(self):
        self.write("AccountService/build/test-results/test/TEST-Old.xml", '<testsuite><testcase classname="Old" name="passed"/></testsuite>')
        run = {"id": "launcher-failure", "source": "local", "branch": "main", "revision": "a", "dirty": False}
        with patch.object(reporting.subprocess, "run", side_effect=OSError("missing launcher")), contextlib.redirect_stdout(io.StringIO()):
            result = reporting.run_module("AccountService", "unit", run, self.root / "out", None)
        self.assertEqual(result["state"], "build_error")
        self.assertEqual(result["exitCode"], 127)
        self.assertEqual(result["tests"]["total"], 0)
        self.assertEqual(result["reportFiles"], 0)

    def test_comment_annotations_are_not_executable_tests(self):
        self.write("AccountService/src/test/java/example/Inactive.java", 'package example; class Inactive { /* @Test */ void x() {} // @Test\n }')
        self.assertEqual(reporting.classify_tests("AccountService"), {"unit": set(), "integration": set()})

    def test_declared_class_name_and_url_survive_comment_parsing(self):
        self.write("AccountService/src/test/java/example/FileNameTest.java", '''package example;
            @Tag("unit")
            class ActualNameTest { String url = "http://localhost"; @Test void x() {} }''')
        self.assertEqual(reporting.classify_tests("AccountService")["unit"], {"example.ActualNameTest"})

    def test_maven_unit_reports_and_project_labels(self):
        self.write("Kosta/target/surefire-reports/TEST-A.xml", '<testsuite><testcase classname="example.A" name="x"/></testsuite>')
        self.write("Kosta/target/failsafe-reports/TEST-B.xml", '<testsuite><testcase classname="example.B" name="integration"/></testsuite>')
        self.write("Kosta/target/site/jacoco-unit/jacoco.xml", '<report><counter type="LINE" missed="5" covered="5"/></report>')
        result = reporting.collect("KostaErpServer", "unit", 0, {"example.A"}, self.root / "out", datetime.now().astimezone(), 1.0, self.root / "Kosta")
        self.assertEqual(result["state"], "passed")
        self.assertEqual(result["tests"]["total"], 1)
        self.assertEqual(result["coverage"]["LINE"]["ratio"], 0.5)
        run = {"project": "KostaErpServer", "source": "local", "branch": "develop", "revision": "a", "dirty": False, "id": "r"}
        self.assertIn('project="KostaErpServer"', reporting.prometheus_text(result, run))

    def test_project_and_branch_are_in_pushgateway_group(self):
        result = {"module": "KostaErpServer"}
        run = {"project": "KostaErpServer", "source": "local", "branch": "feature/tests"}
        import base64
        with patch.object(reporting.urllib.request, "urlopen") as request:
            request.return_value.__enter__.return_value.status = 200
            reporting.push_metrics("http://localhost:9091", result, run, "metric 1\n")
        url = request.call_args.args[0].full_url
        self.assertIn('/project@base64/' + base64.urlsafe_b64encode(b'KostaErpServer').decode(), url)
        self.assertIn('/branch@base64/' + base64.urlsafe_b64encode(b'feature/tests').decode(), url)

    def test_kosta_personal_selection_excludes_other_authors_test(self):
        own = set(reporting.KOSTA_PERSONAL_UNIT_TESTS)
        all_unit = own | {"com.oopsw.kostaerpserver.service.DisposalServiceTest"}
        with patch.object(reporting, "classify_tests", return_value={"unit": all_unit, "integration": {"example.IntegrationTest"}}):
            self.assertEqual(reporting.selected_test_classes("KostaErpServer", "unit", self.root), own)
            self.assertEqual(reporting.selected_test_classes("KostaErpServer", "integration", self.root), {"example.IntegrationTest"})
            self.assertEqual(reporting.selected_test_classes("AccountService", "unit"), all_unit)

    def test_kosta_personal_selection_rejects_missing_class(self):
        with patch.object(reporting, "classify_tests", return_value={"unit": set(), "integration": set()}):
            with self.assertRaisesRegex(ValueError, "본인 작성"):
                reporting.selected_test_classes("KostaErpServer", "unit", self.root)

    def test_class_metrics_count_only_actual_cases_and_include_zero_failures(self):
        result = self.collect()
        result["tests"]["cases"] = [{"class": "example.A", "outcome": "passed"}, {"class": "example.A", "outcome": "failed"}]
        run = {"source": "local", "branch": "main", "revision": "a", "dirty": True, "id": "r"}
        payload = reporting.prometheus_text(result, run)
        self.assertIn('test_class="example.A",result="total"} 2.0', payload)
        self.assertIn('test_class="example.A",result="errors"} 0.0', payload)
        self.assertNotIn('test_class="example.B"', payload)


if __name__ == "__main__":
    unittest.main()
