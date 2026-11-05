#!/usr/bin/env python3
"""Run tagged Spring tests and publish unit-only JUnit/JaCoCo summaries."""
import argparse
import base64
from collections import Counter
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
MODULES = [
    "AccountService", "MenusService", "FoodMaterialsService", "NoticesService",
    "BillsService", "PurchaseService", "DisposalsService", "gatewayServer", "eurekaServer",
]
KOSTA_ROOT = ROOT.parent / "2026_05_KOSTA/KostaErpServer"
# Reviewed with the user against Git history; additions require an ownership review.
# Maven's default test task remains unchanged. Only this publisher selects these classes.
KOSTA_PERSONAL_UNIT_TESTS = frozenset({
    "com.oopsw.kostaerpserver.dto.ocr.BusinessRegistrationResponseTest",
    "com.oopsw.kostaerpserver.service.BusinessDocumentVerificationServiceTest",
    "com.oopsw.kostaerpserver.service.RegistrationServiceTest",
    "com.oopsw.kostaerpserver.service.client.BusinessRegistrationClientTest",
    "com.oopsw.kostaerpserver.service.client.PythonOcrClientTest",
    "com.oopsw.kostaerpserver.service.AuthServiceTest",
    "com.oopsw.kostaerpserver.service.StatisticsServiceTest",
    "com.oopsw.kostaerpserver.service.PhoneVerificationServiceTest",
})
COUNTERS = ("LINE", "BRANCH", "INSTRUCTION", "METHOD", "CLASS")
STATES = {"no_tests": 0, "passed": 1, "failed": 2, "build_error": 3, "skipped": 4}


def git_value(*args, root=None):
    result = subprocess.run(["git", *args], cwd=root or ROOT, text=True, capture_output=True)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def java_without_comments(source):
    # Preserve strings/text blocks (URLs may contain //) while removing comments.
    token = re.compile(r'"""[\s\S]*?"""|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/')
    return token.sub(lambda match: " " if match.group().startswith(("//", "/*")) else match.group(), source)


def classify_tests(module, project_root=None):
    """Require explicit class tags; context/real HTTP tests cannot enter unit results."""
    groups = {"unit": set(), "integration": set()}
    for path in ((project_root or ROOT / module) / "src/test").rglob("*.java"):
        source = java_without_comments(path.read_text())
        if not re.search(r"@(?:org\.junit\.jupiter\.api\.)?(?:Test|ParameterizedTest)\b", source):
            continue
        tags = set(re.findall(r'@(?:org\.junit\.jupiter\.api\.)?Tag\("(unit|integration)"\)', source))
        if len(tags) != 1:
            raise ValueError(f"테스트 클래스에 unit/integration 태그 1개가 필요합니다: {path}")
        suite = tags.pop()
        if suite == "unit" and any(value in source for value in (
            "@SpringBootTest", "AnnotationConfigApplicationContext", "ApplicationContextRunner", "HttpServer.create(",
        )):
            raise ValueError(f"Spring 컨텍스트 테스트는 integration이어야 합니다: {path}")
        package = re.search(r"\bpackage\s+([\w.]+)\s*;", source)
        declaration = re.search(r"^\s*(?:public\s+)?class\s+(\w+)", source, re.M)
        name = declaration.group(1) if declaration else path.stem
        groups[suite].add(f"{package.group(1)}.{name}" if package else name)
    return groups


def selected_test_classes(module, suite, project_root=None):
    classes = classify_tests(module, project_root)[suite]
    if project_root and module == "KostaErpServer" and suite == "unit":
        missing = KOSTA_PERSONAL_UNIT_TESTS - classes
        if missing:
            raise ValueError(f"본인 작성 단위 테스트 목록을 확인해야 합니다: {sorted(missing)}")
        return set(KOSTA_PERSONAL_UNIT_TESTS)
    return classes


def read_junit(paths):
    counts = Counter({"passed": 0, "failed": 0, "errors": 0, "skipped": 0})
    cases = []
    duration = 0.0
    for path in paths:
        root = ET.parse(path).getroot()
        for case in root.iter("testcase"):
            outcome = ("failed" if case.find("failure") is not None else
                       "errors" if case.find("error") is not None else
                       "skipped" if case.find("skipped") is not None else "passed")
            seconds = float(case.get("time", "0"))
            if not math.isfinite(seconds) or seconds < 0:
                raise ValueError(f"잘못된 테스트 시간: {path}")
            duration += seconds
            counts[outcome] += 1
            cases.append({"class": case.get("classname", ""), "name": case.get("name", ""), "outcome": outcome})
    return {"total": sum(counts.values()), **counts, "durationSeconds": duration, "cases": cases}


def read_coverage(path):
    """Use report-level counters once; package/class counters would double-count."""
    root = ET.parse(path).getroot()
    result = {}
    for counter in root.findall("counter"):
        kind = counter.get("type")
        if kind not in COUNTERS:
            continue
        missed, covered = int(counter.get("missed", "0")), int(counter.get("covered", "0"))
        if min(missed, covered) < 0:
            raise ValueError(f"음수 커버리지 카운터: {path}")
        total = missed + covered
        result[kind] = {"missed": missed, "covered": covered, "ratio": covered / total if total else None}
    if "LINE" not in result:
        raise ValueError(f"JaCoCo 보고서에 LINE 집계가 없습니다: {path}")
    return result


def collect(module, suite, return_code, expected, folder, started, elapsed, project_root=None):
    build = (project_root / "target") if project_root else ROOT / module / "build"
    task = "test" if suite == "unit" else "integrationTest"
    reports = build / ("surefire-reports" if suite == "unit" else "failsafe-reports") if project_root else build / "test-results" / task
    paths = sorted(reports.glob("TEST-*.xml"))
    tests = read_junit(paths)
    actual = {case["class"].split("$")[0] for case in tests["cases"]}
    error = None
    if actual - expected:
        error = f"{suite} 결과에 다른 그룹의 클래스가 있습니다: {sorted(actual - expected)}"
    elif expected - actual and return_code == 0:
        error = f"실행 결과에서 클래스가 누락됐습니다: {sorted(expected - actual)}"
    coverage_path = build / ("site/jacoco-unit/jacoco.xml" if project_root else "reports/jacoco/test/jacocoTestReport.xml")
    coverage = None
    executed = tests["passed"] + tests["failed"] + tests["errors"]
    if suite == "unit" and executed > 0 and coverage_path.exists():
        coverage = read_coverage(coverage_path)
    if suite == "unit" and executed > 0 and coverage is None and return_code == 0:
        error = error or "단위 테스트는 실행됐지만 JaCoCo XML 보고서가 없습니다."
    if return_code != 0 or error:
        state = "failed" if tests["failed"] + tests["errors"] > 0 else "build_error"
    elif tests["total"] == 0:
        state = "no_tests"
    elif tests["passed"] == 0 and tests["skipped"] == tests["total"]:
        state = "skipped"
    else:
        state = "passed"
    folder.mkdir(parents=True, exist_ok=True)
    for path in paths:
        shutil.copy2(path, folder / path.name)
    if coverage is not None:
        shutil.copy2(coverage_path, folder / "jacoco.xml")
    return {
        "module": module, "suite": suite, "state": state, "exitCode": return_code,
        "startedAt": started.isoformat(timespec="seconds"),
        "finishedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "finishedTimestamp": time.time(), "buildDurationSeconds": elapsed,
        "expectedClasses": sorted(expected), "reportedClasses": sorted(actual),
        "reportFiles": len(paths), "tests": tests, "coverage": coverage, "error": error,
    }


def escape(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def prometheus_text(result, run):
    common = {"project": run.get("project", "ErpMSA"), "module": result["module"], "source": run["source"], "branch": run["branch"]}
    lines = []

    def metric(name, value, **labels):
        if value is None:
            return
        label_text = ",".join(f'{key}="{escape(val)}"' for key, val in {**common, **labels}.items())
        lines.append(f"{name}{{{label_text}}} {float(value)!r}\n")

    tests = result["tests"]
    metric("erpmsa_unit_test_cases", tests["total"], result="total")
    for outcome in ("passed", "failed", "errors", "skipped"):
        metric("erpmsa_unit_test_cases", tests[outcome], result=outcome)
    for cls in sorted({case["class"] for case in tests.get("cases", [])}):
        cases = [case for case in tests["cases"] if case["class"] == cls]
        metric("erpmsa_unit_test_class_cases", len(cases), test_class=cls, result="total")
        for outcome in ("passed", "failed", "errors", "skipped"):
            metric("erpmsa_unit_test_class_cases", sum(c["outcome"] == outcome for c in cases), test_class=cls, result=outcome)
    executed = tests["passed"] + tests["failed"] + tests["errors"]
    metric("erpmsa_unit_test_success_ratio", tests["passed"] / executed if executed else None)
    metric("erpmsa_unit_test_state", STATES[result["state"]])
    metric("erpmsa_unit_test_build_success", int(result["exitCode"] == 0 and not result["error"]))
    metric("erpmsa_unit_test_report_available", int(result["reportFiles"] > 0))
    metric("erpmsa_unit_test_coverage_available", int(result["coverage"] is not None))
    metric("erpmsa_unit_test_finished_timestamp_seconds", result["finishedTimestamp"])
    metric("erpmsa_unit_test_duration_seconds", tests["durationSeconds"])
    metric("erpmsa_unit_test_build_duration_seconds", result["buildDurationSeconds"])
    metric("erpmsa_unit_test_info", 1, revision=run["revision"], dirty=str(run["dirty"]).lower(), run_id=run["id"], test_selection=run.get("testSelection", "all-tagged"))
    for counter, values in (result["coverage"] or {}).items():
        metric("erpmsa_unit_test_coverage_ratio", values["ratio"], counter=counter)
        for outcome in ("covered", "missed"):
            metric("erpmsa_unit_test_coverage", values[outcome], counter=counter, result=outcome)
    return "".join(lines)


def push_metrics(base_url, result, run, text):
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Pushgateway는 인증정보를 포함하지 않은 HTTP(S) 기본 URL이어야 합니다.")
    url = base_url.rstrip("/") + "/metrics/job/spring_unit_tests"
    for key, value in {"project": run.get("project", "ErpMSA"), "module": result["module"], "source": run["source"], "branch": run["branch"]}.items():
        encoded = base64.urlsafe_b64encode(value.encode()).decode()
        url += f"/{key}@base64/{encoded}"
    request = urllib.request.Request(url, data=text.encode(), method="PUT", headers={"Content-Type": "text/plain; version=0.0.4"})
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError(f"Pushgateway HTTP {response.status}")


def run_module(module, suite, run, out, pushgateway, project_root=None):
    folder = out / suite / module
    folder.mkdir(parents=True, exist_ok=True)
    classes = selected_test_classes(module, suite, project_root)
    task = "test" if suite == "unit" else "integrationTest"
    command = [str(ROOT / module / "gradlew"), "-p", str(ROOT / module),
               ":cleanTest" if suite == "unit" else ":cleanIntegrationTest", ":" + task, "--no-daemon"]
    # Remove generated reports before launching Gradle, including launcher failures.
    generated = [ROOT / module / "build/test-results" / task,
                 ROOT / module / "build/reports/tests" / task]
    if suite == "unit":
        generated += [ROOT / module / "build/jacoco/test.exec", ROOT / module / "build/reports/jacoco/test"]
    if project_root:
        command = ["sh", str(project_root / "mvnw"), "-B", "-ntp"]
        command += ["-Dtest=" + ",".join(sorted(classes)), "test"] if suite == "unit" else ["-DskipUnitTests=true", "verify"]
        generated = [project_root / "target" / ("surefire-reports" if suite == "unit" else "failsafe-reports")]
        if suite == "unit":
            generated += [project_root / "target/jacoco-unit.exec", project_root / "target/site/jacoco-unit"]
    for path in generated:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    environment = dict(os.environ, ERPMSA_VERIFICATION_RUN_ID=run["id"])
    if project_root and suite == "unit":
        # Unit tests must run independently of any configured developer database.
        environment.update(DB_URL="jdbc:mariadb://127.0.0.1:1/unit_tests_do_not_use_db",
                           SPRING_DATASOURCE_URL="jdbc:mariadb://127.0.0.1:1/unit_tests_do_not_use_db",
                           DB_USERNAME="unit_test", DB_PASSWORD="unused")
    started = datetime.now().astimezone()
    clock = time.monotonic()
    print(f"[{suite}] {module}: 실행 ({len(classes)} classes)", flush=True)
    with (folder / "gradle.log").open("w") as log:
        try:
            completed = subprocess.run(command, cwd=project_root or ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=900)
            return_code = completed.returncode
        except subprocess.TimeoutExpired:
            return_code = 124
        except OSError as error:
            log.write(f"빌드 실행 실패: {error}\n")
            return_code = 127
    try:
        result = collect(module, suite, return_code, classes, folder, started, time.monotonic() - clock, project_root)
    except (OSError, ValueError, ET.ParseError) as error:
        result = {
            "module": module, "suite": suite, "state": "build_error", "exitCode": return_code or 2,
            "startedAt": started.isoformat(timespec="seconds"),
            "finishedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "finishedTimestamp": time.time(), "buildDurationSeconds": time.monotonic() - clock,
            "expectedClasses": sorted(classes), "reportedClasses": [], "reportFiles": 0,
            "tests": read_junit([]), "coverage": None, "error": str(error),
        }
    result["command"] = command
    result["testSelection"] = "personal-kosta-unit" if project_root and suite == "unit" else "all-tagged"
    if suite == "unit":
        metrics = prometheus_text(result, run)
        (folder / "metrics.prom").write_text(metrics)
        if pushgateway:
            try:
                push_metrics(pushgateway, result, run, metrics)
                result["pushed"] = True
            except (ValueError, OSError, RuntimeError, urllib.error.URLError) as error:
                result["pushed"] = False
                result["pushError"] = str(error)
    (folder / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"[{suite}] {module}: {result['state']} / tests={result['tests']['total']} / failures={result['tests']['failed'] + result['tests']['errors']}", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", choices=["ErpMSA", "KostaErpServer"], default="ErpMSA")
    parser.add_argument("--project-root", type=Path, help="KostaErpServer Maven repository path")
    parser.add_argument("--suite", choices=["unit", "integration", "all"], default="unit")
    parser.add_argument("--modules", nargs="+", choices=MODULES + ["KostaErpServer"])
    parser.add_argument("--source", default="local", help="Metric source, e.g. local or jenkins")
    parser.add_argument("--branch", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--pushgateway", help="Publish unit-only metrics to this Pushgateway")
    args = parser.parse_args()
    project_root = (args.project_root or KOSTA_ROOT).expanduser().resolve() if args.project == "KostaErpServer" else None
    if args.project_root and not project_root:
        parser.error("--project-root는 KostaErpServer에만 사용합니다.")
    if project_root and not (project_root / "pom.xml").is_file():
        parser.error(f"Maven 프로젝트를 찾을 수 없습니다: {project_root}")
    allowed = ["KostaErpServer"] if project_root else MODULES
    modules = args.modules or allowed
    if set(modules) - set(allowed):
        parser.error("선택한 프로젝트에 속하지 않는 모듈입니다.")
    revision_root = project_root or ROOT
    run = {
        "project": args.project,
        "testSelection": "personal-kosta-unit" if project_root and args.suite in ("unit", "all") else "all-tagged",
        "id": args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6],
        "source": args.source, "branch": args.branch or git_value("branch", "--show-current", root=revision_root) or "unknown",
        "revision": git_value("rev-parse", "HEAD", root=revision_root), "dirty": bool(git_value("status", "--porcelain", root=revision_root)),
        "startedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scope": "project src/main" if project_root else "root service src/main only; shared libraries excluded from coverage",
    }
    out = args.out or ROOT / ".verification/spring-tests" / args.project / run["id"]
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    for module in modules:
        classify_tests(module, project_root)
    suites = ["unit", "integration"] if args.suite == "all" else [args.suite]
    results = []
    try:
        for suite in suites:
            for module in modules:
                results.append(run_module(module, suite, run, out, args.pushgateway, project_root))
    finally:
        run["finishedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
        (out / "summary.json").write_text(json.dumps({"run": run, "results": results}, ensure_ascii=False, indent=2) + "\n")
        (out / "metrics.prom").write_text("".join(prometheus_text(r, run) for r in results if r["suite"] == "unit"))
    print(f"결과: {out}", flush=True)
    return int(any(r["state"] in ("failed", "build_error") or r.get("pushed") is False for r in results))


if __name__ == "__main__":
    sys.exit(main())
