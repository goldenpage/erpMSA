#!/usr/bin/env python3
"""Verify reviewed Kosta personal Spring tests, recorded APIs and OpenAPI scope."""
import argparse
import base64
from collections import Counter
from datetime import datetime
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import time
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
KOSTA = ROOT.parent / "2026_05_KOSTA/KostaErpServer"
PREFIX = "com.oopsw.kostaerpserver."
TESTS = {PREFIX + "repository.StatisticsDAOTest": "statistics_repository"}
SMOKE_TEST = PREFIX + "KostaErpServerApplicationTests"
ACCOUNT_TESTS = {
    PREFIX + "repository.UserinfoDAOTest": ("member_repository", 7),
    PREFIX + "service.RegistrationReviewServiceTest": ("registration_review", 2),
    PREFIX + "repository.entity.RegistrationRequestedUserRepositoryTest": ("registration_repository", 3),
    PREFIX + "repository.entity.AdminUserDAOTest": ("admin_repository", 1),
}
REVIEWED_FILES = ["src/test/java/com/oopsw/kostaerpserver/service/StatisticsServiceTest.java",
                  "src/test/java/com/oopsw/kostaerpserver/repository/StatisticsDAOTest.java",
                  "src/main/java/com/oopsw/kostaerpserver/advice/restcontroller/StatisticsRestController.java",
                  "src/main/java/com/oopsw/kostaerpserver/OpenApiConfig.java"]
REVIEWED_FILES += ["src/test/java/" + name.replace(".", "/") + ".java" for name in ACCOUNT_TESTS]
OWNERS = {"jong845", "JongHwan"}
EXPECTED_API = {
    "/api/statistics/disposals/rate": {"disposalRate": 10},
    "/api/statistics/disposals/top-materials": [{"foodMaterialId": "FM001", "foodMaterialName": "테스트양파", "disposalCount": 1, "totalDisposalPrice": 500}],
    "/api/statistics/disposals/reason-ratio": [{"reasonId": "E", "reason": "유통기한", "reasonCount": 1, "reasonRatio": 100}],
    "/api/statistics/disposals/daily-chart": [{"disposalDay": "2026-05-15", "foodMaterialType": "고체", "disposalCount": 100, "totalDisposalPrice": 500}],
    "/api/statistics/expenses/material-rank": [{"ranking": 1, "foodMaterialName": "테스트양파", "foodMaterialPrice": 200, "foodMaterialCount": 10, "totalExpense": 2000}],
    "/api/statistics/expenses/material-rank/chart": [{"ranking": 1, "foodMaterialName": "테스트양파", "totalExpense": 2000}],
    "/api/statistics/revenue/history": [{"saleId": "S05", "saleMenuCount": 2, "menuId": "M001", "menuName": "테스트메뉴", "menuPrice": 3000, "revenueId": "RV05", "revenueDate": "2026-05-15", "saleTotalPrice": 6000}],
    "/api/statistics/revenue/menu-rank": [{"ranking": 1, "menuId": "M001", "menuName": "테스트메뉴", "menuPrice": 3000, "totalSaleCount": 2, "totalSalePrice": 6000}],
}
spec = importlib.util.spec_from_file_location("spring_reporting", ROOT / "scripts/run-spring-tests.py")
reporting = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporting)
REVIEWED_FILES = list(dict.fromkeys(REVIEWED_FILES + [
    "src/test/java/" + name.replace(".", "/") + ".java"
    for name in sorted(reporting.KOSTA_PERSONAL_UNIT_TESTS)
]))


def test_methods(source):
    """Find active JUnit method bodies and line ranges, ignoring comments/literals."""
    token = re.compile(r'"""[\s\S]*?"""|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/')
    masked = token.sub(lambda m: re.sub(r'[^\n]', ' ', m[0]), source)
    methods = []
    for match in re.finditer(r'@Test\b(?:(?!@Test)[\s\S])*?\bvoid\s+(\w+)\s*\([^)]*\)[^{]*\{', masked):
        start, end, depth = match.end() - 1, match.end(), 1
        while depth and end < len(masked):
            depth += (masked[end] == '{') - (masked[end] == '}')
            end += 1
        if depth:
            raise ValueError("테스트 메서드 본문 범위를 확인할 수 없습니다.")
        methods.append((match[1], source.count('\n', 0, start), source.count('\n', 0, end)))
    return methods


def audit_inventory(project):
    """Audit every test body, so personal import edits cannot claim teammate tests."""
    selected = set(reporting.KOSTA_PERSONAL_UNIT_TESTS) | set(TESTS) | set(ACCOUNT_TESTS)
    groups = reporting.classify_tests("KostaErpServer", project)
    inventory = []
    for path in sorted((project / "src/test").rglob("*.java")):
        relative = str(path.relative_to(project))
        blame = command(["git", "blame", "--line-porcelain", "HEAD", "--", relative], cwd=project)
        authors, lines, author = [], [], None
        for line in blame.splitlines():
            if line.startswith("author "):
                author = line[7:]
            elif line.startswith("\t"):
                authors.append(author)
                lines.append(line[1:])
        original = '\n'.join(lines)
        current = path.read_text()
        package = re.search(r'\bpackage\s+([\w.]+);', current)[1]
        cls = package + '.' + re.search(r'^\s*(?:public\s+)?class\s+(\w+)', current, re.M)[1]
        methods = test_methods(original)
        own = [name for name, start, end in methods
               if {authors[i] for i in range(start, end + 1) if lines[i].strip()} <= OWNERS]
        if cls != SMOKE_TEST and bool(own) != (cls in selected):
            raise ValueError(f"본인 테스트 목록에 누락 또는 잘못된 포함이 있습니다: {cls}")
        if cls in selected and (len(own) != len(methods) or {m[0] for m in test_methods(current)} != set(own)):
            raise ValueError(f"원본 본인 테스트 메서드 범위가 다릅니다: {cls}")
        suite = next((group for group, classes in groups.items() if cls in classes), "inactive")
        inventory.append({"class": cls, "path": relative, "originalMethods": [m[0] for m in methods],
                          "personalMethods": own, "suite": suite, "selected": cls in selected,
                          "scope": "generated-context-smoke" if cls == SMOKE_TEST else "personal" if cls in selected else "teammate-or-inactive",
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return inventory


def command(args, log=None, **kwargs):
    result = subprocess.run(args, text=True, stdout=log or subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=kwargs.pop("timeout", 300), **kwargs)
    if result.returncode:
        raise RuntimeError(f"명령 실패(exit={result.returncode}): {args[0]} (상세 로그 확인)")
    return result.stdout or ""


def history_evidence(path):
    result = {route: [] for route in EXPECTED_API}
    if path.exists():
        for line_number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            for route in set(re.findall(r"/api/statistics/[A-Za-z0-9_/-]+", line)) & result.keys():
                result[route].append(line_number)
    return {"available": path.exists(), "routes": result, "status": "request-observed; historical-response-not-verified"}


def provenance(project):
    result = []
    for relative in REVIEWED_FILES:
        source = project / relative
        blame = command(["git", "blame", "--line-porcelain", "HEAD", "--", relative], cwd=project)
        authors = set(re.findall(r"^author ([^\n]+)", blame, re.M))
        ownership = "reviewed-file"
        if relative.endswith("StatisticsRestController.java"):
            current_author, routes = None, []
            for line in blame.splitlines():
                if line.startswith("author "):
                    current_author = line[len("author "):]
                elif line.startswith("\t") and ("@GetMapping(" in line or "statisticsService.get" in line):
                    routes.append(current_author)
            if len(routes) < 26 or set(routes) - OWNERS:
                raise ValueError("통계 경로·서비스 호출의 본인 작성 이력을 확인해야 합니다.")
            ownership = "personal-statistics-routes; teammate-authentication-edits-excluded"
        elif not authors or authors - OWNERS:
            raise ValueError(f"본인 작성 범위를 다시 확인해야 합니다: {relative}")
        result.append({"path": relative, "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                       "gitAuthorsReviewed": True, "ownership": ownership})
    return result


def token(secret):
    def part(value):
        return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=")
    now = int(time.time())
    message = part({"alg": "HS256", "typ": "JWT"}) + b"." + part({"sub": "0000000000", "role": "ROLE_USER", "iat": now, "exp": now + 1800})
    return (message + b"." + base64.urlsafe_b64encode(hmac.new(secret.encode(), message, hashlib.sha256).digest()).rstrip(b"=")).decode()


def account_fixture(password="test123"):
    if password not in ("test123", "kim123!"):
        raise ValueError("허용된 합성 fixture 비밀번호가 아닙니다.")
    return """DELETE FROM account; DELETE FROM admin_user;
DELETE FROM registration_requested_user; DELETE FROM USERINFO;
INSERT INTO USERINFO (bId,name,phone,email,storeName,storeType,storeCategory,pw,signDate,agreementDate)
VALUES ('0000000000','김사장','01000000000','fixture@example.invalid','합성가게','음식점','한식','""" + password + "',NOW(),NOW());"


def run_account_tests(project, environment, out, reset_database):
    """Preserve source assertions; reset synthetic prerequisites between independent cases."""
    results = {}
    reports = project / "target/failsafe-reports"
    for cls, (kind, expected_count) in ACCOUNT_TESTS.items():
        # Legacy DAO tests explicitly expect different passwords. Each method gets
        # its own documented precondition, instead of relying on execution order.
        methods = ["loginTest", "register", "checkMemberByVO", "setPw", "getPhoneCheck", "getBidCheck", "checkPwFindUser"] if kind == "member_repository" else [None]
        cases = []
        for method in methods:
            reset_database(account_fixture("kim123!" if method == "checkMemberByVO" else "test123"))
            if reports.exists():
                shutil.rmtree(reports)
            selected = cls + ("#" + method if method else "")
            folder = out / "account-tests" / kind / (method or "class")
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / "maven.log").open("w") as log:
                build = subprocess.run(["sh", str(project / "mvnw"), "-B", "-ntp", "-DskipUnitTests=true", "-Dit.test=" + selected,
                                        "test-compile", "failsafe:integration-test", "failsafe:verify"], cwd=project, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=180)
            tests = reporting.read_junit(sorted(reports.glob("TEST-*.xml")))
            if {case["class"] for case in tests["cases"]} != {cls}:
                raise ValueError(f"계정 테스트 클래스 범위가 다릅니다: {kind}")
            if method and (len(tests["cases"]) != 1 or tests["cases"][0]["name"].split("(")[0] != method):
                raise ValueError("회원 DAO의 독립 테스트 선택이 다릅니다.")
            for p in reports.glob("TEST-*.xml"):
                shutil.copy2(p, folder / p.name)
            cases += tests["cases"]
            if build.returncode:
                raise RuntimeError(f"계정 테스트 실패: {kind}/{method or 'class'}")
        counts = Counter(c["outcome"] for c in cases)
        if len(cases) != expected_count:
            raise ValueError(f"계정 테스트 실행 건수가 다릅니다: {kind}")
        if counts["passed"] != expected_count:
            raise ValueError(f"계정 테스트에 실패·오류·건너뜀이 있습니다: {kind}")
        results[kind] = {"total": len(cases), **{k: counts[k] for k in ["passed", "failed", "errors", "skipped"]}}
        print(f"{kind}: {counts['passed']}/{expected_count} 통과", flush=True)
    return results


def collection():
    items = []
    for route, expected in EXPECTED_API.items():
        script = [
            'pm.test("HTTP 200", function () { pm.response.to.have.status(200); });',
            'pm.test("Synthetic fixture values and tenant isolation", function () {',
            '  const actual = pm.response.json();',
            '  const expected = ' + json.dumps(expected, ensure_ascii=False) + ';',
            '  if (Array.isArray(expected)) { pm.expect(actual).to.have.lengthOf(expected.length); expected.forEach((item, i) => pm.expect(actual[i]).to.include(item)); }',
            '  else { pm.expect(actual).to.include(expected); }',
            '});',
        ]
        items.append({"name": route, "request": {"method": "GET", "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{accessToken}}", "type": "string"}]},
                      "url": "{{baseUrl}}" + route + "?startDate=2026-05-01&endDate=2026-06-01"},
                      "event": [{"listen": "test", "script": {"type": "text/javascript", "exec": script}}]})
    return {"info": {"name": "Kosta personal statistics - reconstructed replay", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
                     "description": "Eight recorded user-owned APIs. Fixture assertions added for this replay; not the original historical collection."}, "item": items}


def summarize_newman(data):
    result = []
    for execution in data["run"]["executions"]:
        endpoint = execution["item"]["name"]
        if endpoint not in EXPECTED_API:
            raise ValueError("본인 검증 범위 밖의 Newman API입니다.")
        assertions = execution.get("assertions", [])
        errors = [a["assertion"] for a in assertions if a.get("error")]
        status = execution.get("response", {}).get("code", 0)
        passed = status == 200 and len(assertions) == 2 and not errors and not any(a.get("skipped") for a in assertions) and not execution.get("requestError")
        result.append({"endpoint": endpoint, "httpStatus": status, "passed": passed, "assertions": len(assertions), "failedAssertions": errors})
    if {r["endpoint"] for r in result} != set(EXPECTED_API) or len(result) != 8:
        raise ValueError("Newman API 실행이 8개와 일치하지 않습니다.")
    return result


def check_swagger(base_url, project):
    with urllib.request.urlopen(base_url + "/v3/api-docs", timeout=30) as response:
        document = json.load(response)
    controller = (project / REVIEWED_FILES[2]).read_text()
    routes = ["/api/statistics" + route for route in re.findall(r'@GetMapping\("([^"]+)"\)', controller)]
    entries = []
    for route, method, source in [(r, "get", "controller-generated") for r in routes] + [("/api/auth/login", "post", "explicit-openapi")]:
        operation = document.get("paths", {}).get(route, {}).get(method, {})
        entries.append({"endpoint": route, "method": method.upper(), "documented": bool(operation.get("responses", {}).get("200")), "source": source})
    bearer = document.get("components", {}).get("securitySchemes", {}).get("bearerAuth", {})
    login = document.get("paths", {}).get("/api/auth/login", {}).get("post", {})
    schema = login.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
    headers = login.get("responses", {}).get("200", {}).get("headers", {})
    with urllib.request.urlopen(base_url + "/swagger-ui/index.html", timeout=15) as response:
        ui_ok = response.status == 200 and "Swagger UI" in response.read().decode()
    checks = {"openapi3": str(document.get("openapi", "")).startswith("3."), "bearerJwt": bearer.get("scheme") == "bearer" and bearer.get("bearerFormat") == "JWT",
              "loginRequestSchema": {"username", "password"}.issubset(schema.get("required", [])),
              "loginResponseHeaders": {"Authorization", "Set-Cookie"}.issubset(headers), "swaggerUi": ui_ok}
    return {"routes": entries, "checks": checks, "expectedRoutes": len(routes) + 1,
            "passed": all(x["documented"] for x in entries) and all(checks.values())}


def metrics(summary):
    lines = []
    common = {"project": "KostaErpServer", "source": "local", "branch": summary["branch"], "scope": "personal"}
    def metric(name, value, **labels):
        label = ",".join(f'{k}="{reporting.escape(v)}"' for k, v in {**common, **labels}.items())
        lines.append(f"{name}{{{label}}} {float(value)}\n")
    for kind, counts in {**summary.get("statistics", {}), **summary.get("accounts", {})}.items():
        for outcome in ("total", "passed", "failed", "errors", "skipped"):
            metric("erpmsa_personal_verification_cases", counts[outcome], kind=kind, suite="integration", result=outcome)
    for outcome in ("total", "passed", "failed", "errors", "skipped"):
        if "contextSmoke" in summary:
            metric("erpmsa_personal_context_smoke_cases", summary["contextSmoke"][outcome], result=outcome)
    for route, records in summary["postmanHistory"]["routes"].items():
        metric("erpmsa_personal_postman_history", int(bool(records)), endpoint=route)
    for result in summary.get("postmanReplay", []):
        metric("erpmsa_personal_postman_passed", int(result["passed"]), endpoint=result["endpoint"])
        metric("erpmsa_personal_postman_http_status", result["httpStatus"], endpoint=result["endpoint"])
        metric("erpmsa_personal_postman_assertions", result["assertions"], endpoint=result["endpoint"])
    for result in summary.get("swagger", {}).get("routes", []):
        metric("erpmsa_personal_swagger_documented", int(result["documented"]), endpoint=result["endpoint"], method=result["method"], documentation=result["source"])
    for check, passed in summary.get("swagger", {}).get("checks", {}).items():
        metric("erpmsa_personal_swagger_check", int(passed), check=check)
    metric("erpmsa_personal_verification_success", int(summary.get("success", False)))
    metric("erpmsa_personal_verification_finished_timestamp_seconds", summary["finishedTimestamp"])
    metric("erpmsa_personal_verification_info", 1, revision=summary["revision"], run_id=summary["id"])
    return "".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=KOSTA)
    parser.add_argument("--run-id", default="kosta-verification-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--postman-log", type=Path, default=Path.home() / "Library/Application Support/Postman/logs/renderer-requester.log")
    parser.add_argument("--pushgateway", default="http://127.0.0.1:9091")
    args = parser.parse_args()
    project = args.project_root.resolve()
    out = ROOT / ".verification/kosta-personal" / args.run_id
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    summary = {"id": args.run_id, "startedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
               "branch": reporting.git_value("branch", "--show-current", root=project), "revision": reporting.git_value("rev-parse", "HEAD", root=project),
               "dirty": bool(reporting.git_value("status", "--porcelain", root=project)),
               "provenance": provenance(project), "testInventory": audit_inventory(project),
               "postmanHistory": history_evidence(args.postman_log), "statistics": {}}
    name = "erpmsa-kosta-verify-" + uuid.uuid4().hex[:10]
    db_password, jwt_secret = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    environment_file, auth_file = out / "database.env", out / "newman-environment.json"
    environment_file.write_text(f"MARIADB_ROOT_PASSWORD={db_password}\nMARIADB_DATABASE=kosta_verify\n")
    environment_file.chmod(0o600)
    raw_report = out / "newman-raw.json"
    app = None
    created = False
    unit_xml = project / "target/site/jacoco-unit/jacoco.xml"
    unit_hash = None
    try:
        print("본인 단위 테스트 8개 클래스·38건 실행 (Spring·DB 없이 Mock/Stub 사용)", flush=True)
        unit_id = args.run_id + "-unit"
        unit_command = ["python3", str(ROOT / "scripts/run-spring-tests.py"), "--project", "KostaErpServer", "--project-root", str(project),
                        "--suite", "unit", "--run-id", unit_id]
        if args.pushgateway:
            unit_command += ["--pushgateway", args.pushgateway]
        with (out / "unit-runner.log").open("w") as log:
            command(unit_command, cwd=ROOT, log=log, timeout=300)
        unit = json.loads((ROOT / ".verification/spring-tests/KostaErpServer" / unit_id / "summary.json").read_text())["results"][0]
        summary["unit"] = unit
        (out / "unit-summary.json").write_text(json.dumps(unit, ensure_ascii=False, indent=2) + "\n")
        expected_units = {row["class"]: len(row["personalMethods"]) for row in summary["testInventory"] if row["selected"] and row["suite"] == "unit"}
        actual_units = Counter(case["class"] for case in unit["tests"]["cases"])
        if unit["state"] != "passed" or actual_units != expected_units or unit["tests"]["passed"] != 38:
            raise ValueError("본인 단위 테스트의 원본 메서드·실행 건수가 일치하지 않습니다.")
        unit_hash = hashlib.sha256(unit_xml.read_bytes()).hexdigest()
        print("단위 테스트 38/38 통과, 단위 JaCoCo 새로 생성", flush=True)
        command(["docker", "run", "-d", "--rm", "--name", name, "--label", "erpmsa.verification.run=" + args.run_id,
                 "--tmpfs", "/var/lib/mysql:rw,nosuid,size=512m", "--env-file", str(environment_file), "-p", "127.0.0.1::3306", "mariadb:10.11"])
        created = True
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            ready = subprocess.run(["docker", "exec", name, "healthcheck.sh", "--connect", "--innodb_initialized"], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("격리 MariaDB 준비 시간 초과")
        port = int(command(["docker", "port", name, "3306/tcp"]).strip().rsplit(":", 1)[1])
        command(["docker", "exec", "-i", "-e", "MYSQL_PWD=" + db_password, name, "mariadb", "--default-character-set=utf8mb4", "-uroot", "kosta_verify"],
                input=(ROOT / "scripts/fixtures/kosta-statistics.sql").read_text())
        environment = dict(os.environ, DB_URL=f"jdbc:mariadb://127.0.0.1:{port}/kosta_verify", DB_USERNAME="root", DB_PASSWORD=db_password,
                           SPRING_DATASOURCE_URL=f"jdbc:mariadb://127.0.0.1:{port}/kosta_verify",
                           JWT_SECRET=jwt_secret, SPRING_JPA_HIBERNATE_DDL_AUTO="none", SPRING_PROFILES_ACTIVE="test")
        reports = project / "target/failsafe-reports"
        if reports.exists():
            shutil.rmtree(reports)
        # The generated contextLoads case is executed but kept outside authored business totals.
        reset_sql = (ROOT / "scripts/fixtures/kosta-account.sql").read_text()
        command(["docker", "exec", "-i", "-e", "MYSQL_PWD=" + db_password, name, "mariadb", "--default-character-set=utf8mb4", "-uroot", "kosta_verify"], input=reset_sql)
        print("통계 레포지토리 11건 + 기본 컨텍스트 확인 1건 실행 (격리 MariaDB)", flush=True)
        with (out / "statistics-maven.log").open("w") as log:
            build = subprocess.run(["sh", str(project / "mvnw"), "-B", "-ntp", "-DskipUnitTests=true", "-Dit.test=" + ",".join([*TESTS, SMOKE_TEST]),
                                    "test-compile", "failsafe:integration-test", "failsafe:verify"], cwd=project, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=180)
        tests = reporting.read_junit(sorted(reports.glob("TEST-*.xml")))
        if {case["class"] for case in tests["cases"]} != set(TESTS) | {SMOKE_TEST}:
            raise ValueError("통계 레포지토리·컨텍스트 테스트 클래스 범위가 다릅니다.")
        for cls, kind in TESTS.items():
            cases = [c for c in tests["cases"] if c["class"] == cls]
            counts = Counter(c["outcome"] for c in cases)
            summary["statistics"][kind] = {"total": len(cases), **{k: counts[k] for k in ["passed", "failed", "errors", "skipped"]}}
            if len(cases) != 11:
                raise ValueError("통계 클래스별 실행 건수가 11개와 다릅니다.")
        for p in reports.glob("TEST-*.xml"):
            shutil.copy2(p, out / p.name)
        smoke_cases = [case for case in tests["cases"] if case["class"] == SMOKE_TEST]
        summary["contextSmoke"] = {"total": len(smoke_cases), **{k: sum(c["outcome"] == k for c in smoke_cases) for k in ("passed", "failed", "errors", "skipped")}}
        if build.returncode or tests["passed"] != 12 or summary["contextSmoke"]["passed"] != 1:
            raise RuntimeError("통계 테스트 실패: 보고서 확인")
        print("통계 레포지토리 11/11, 기본 컨텍스트 1/1 통과", flush=True)
        def reset_database(sql):
            command(["docker", "exec", "-i", "-e", "MYSQL_PWD=" + db_password, name, "mariadb", "--default-character-set=utf8mb4", "-uroot", "kosta_verify"], input=sql)
        print("본인 가입 심사·회원 레포지토리 통합 테스트 13건 실행", flush=True)
        summary["accounts"] = run_account_tests(project, environment, out, reset_database)
        with (out / "package.log").open("w") as log:
            command(["sh", str(project / "mvnw"), "-B", "-ntp", "-DskipTests", "-Djacoco.skip=true", "package"], cwd=project, env=environment, log=log, timeout=180)
        with (out / "application.log").open("w") as log:
            app = subprocess.Popen(["java", "-jar", str(project / "target/KostaErpServer-0.0.1-SNAPSHOT.jar"), "--server.address=127.0.0.1", "--server.port=0"],
                                   cwd=out, env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        deadline, base_url = time.monotonic() + 90, None
        while time.monotonic() < deadline:
            text = (out / "application.log").read_text()
            match = re.search(r"Tomcat started on port (\d+)", text)
            if match:
                base_url = "http://127.0.0.1:" + match.group(1)
                break
            if app.poll() is not None:
                raise RuntimeError("격리 Spring 애플리케이션 시작 실패")
            time.sleep(0.5)
        if not base_url:
            raise RuntimeError("격리 Spring 애플리케이션 준비 시간 초과")
        summary["swagger"] = check_swagger(base_url, project)
        (out / "postman-replay.collection.json").write_text(json.dumps(collection(), ensure_ascii=False, indent=2))
        auth_file.write_text(json.dumps({"values": [{"key": "baseUrl", "value": base_url}, {"key": "accessToken", "value": token(jwt_secret)}]}))
        auth_file.chmod(0o600)
        print("Postman 기록 API 8종을 Newman으로 합성 데이터와 대조, Swagger 본인 문서 범위 확인", flush=True)
        with (out / "newman.log").open("w") as log:
            newman = subprocess.run(["npm", "exec", "--yes", "--package=newman@6.2.1", "--", "newman", "run", str(out / "postman-replay.collection.json"),
                                     "-e", str(auth_file), "--reporters", "cli,json", "--reporter-json-export", str(raw_report)],
                                    cwd=out, stdout=log, stderr=subprocess.STDOUT, timeout=180)
        summary["postmanReplay"] = summarize_newman(json.loads(raw_report.read_text()))
        summary["unitCoverageUnchanged"] = unit_hash is None or hashlib.sha256(unit_xml.read_bytes()).hexdigest() == unit_hash
        summary["success"] = newman.returncode == 0 and all(x["passed"] for x in summary["postmanReplay"]) and summary["swagger"]["passed"] and summary["unitCoverageUnchanged"]
    except Exception as error:
        summary["error"] = str(error)
        summary["success"] = False
    finally:
        if app is not None and app.poll() is None:
            os.killpg(app.pid, signal.SIGTERM)
            try:
                app.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(app.pid, signal.SIGKILL)
        if created:
            cleanup = subprocess.run(["docker", "rm", "-f", name], capture_output=True)
            summary["databaseRemoved"] = cleanup.returncode == 0
            if not summary["databaseRemoved"]:
                summary["success"] = False
        for path in (environment_file, auth_file, raw_report):
            path.unlink(missing_ok=True)
        summary["finishedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
        summary["finishedTimestamp"] = time.time()
        (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        payload = metrics(summary)
        (out / "metrics.prom").write_text(payload)
        if args.pushgateway:
            url = args.pushgateway.rstrip("/") + "/metrics/job/kosta_personal_verification/project/KostaErpServer/source/local"
            request = urllib.request.Request(url, data=payload.encode(), method="PUT", headers={"Content-Type": "text/plain; version=0.0.4"})
            with urllib.request.urlopen(request, timeout=15) as response:
                if response.status != 200:
                    raise RuntimeError("검증 지표 전송 실패")
    print("결과:", out, "PASS" if summary["success"] else "FAIL", flush=True)
    if summary.get("error"):
        print(summary["error"], flush=True)
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
