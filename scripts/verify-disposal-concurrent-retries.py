#!/usr/bin/env python3
"""Verify both concurrent disposal retries in fresh local MSA runtimes with real A2A agents."""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, suppress
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
from threading import Barrier, Event, Lock, Thread
import time
import traceback
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import investigate_disposal as cli
from disposal_a2a import CARD_PATH, TOKEN_ENV as A2A_TOKEN_ENV, MetricsA2AClient
from disposal_metrics import QUERIES


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ("before-deduction", "lost-stock-response")
ISSUER = "concurrent-retry-test"
DB_USER = "retry_fixture"
SERVICES = {
    "foodmaterials-service": ("FoodMaterialsService", "FOOD_MATERIAL"),
    "disposals-service": ("DisposalsService", "DISPOSALS"),
    "gateway-server": ("gatewayServer", "GATEWAY"),
}
SCHEMAS = (
    ("mydb", "AccountService/src/main/resources/db/migration/V1__create_account_schema.sql"),
    ("itemdb", "FoodMaterialsService/src/main/resources/db/migration/V1__create_item_schema.sql"),
    ("itemdb", "FoodMaterialsService/src/main/resources/db/migration/V2__index_item_status_created.sql"),
    ("inventorydb", "FoodMaterialsService/src/main/resources/db/inventory-migration/V1__create_inventory_schema.sql"),
    ("disposalsdb", "DisposalsService/src/main/resources/db/migration/V1__create_disposal_schema.sql"),
    ("disposalsdb", "scripts/sql/create-legacy-disposal-history.sql"),
)
STOCK_SQL = """
SELECT * FROM inventorydb.inventory ORDER BY id;
SELECT * FROM inventorydb.stock_movement ORDER BY id;
"""
STABLE_SQL = """
SELECT * FROM mydb.account ORDER BY id;
SELECT * FROM itemdb.item ORDER BY id;
""" + STOCK_SQL + "SELECT * FROM disposalsdb.disposal ORDER BY id;"
ARCHIVE_SQL = """
SELECT JSON_OBJECT(
    'legacyDisposalId', legacy_disposal_id, 'legacyAccountId', legacy_account_id,
    'legacyFoodMaterialId', legacy_food_material_id, 'legacyReasonId', legacy_reason_id,
    'reason', reason, 'quantity', quantity, 'legacyPrice', legacy_price,
    'disposedAt', legacy_disposed_at, 'accountId', account_id, 'foodMaterialId', food_material_id)
FROM disposalsdb.legacy_disposal_history ORDER BY BINARY legacy_disposal_id;
"""
RESTORE_SQL = """
INSERT INTO mydb.account
    (b_id, created_at, email, marketing_agreed, name, pw_hash, review_status, role, store_name, updated_at, username)
SELECT owner, '2026-11-09', CONCAT('isolated-', ROW_NUMBER() OVER (ORDER BY owner), '@example.invalid'),
       0, 'Isolated legacy account', 'DISABLED', 'SUSPENDED', 'ROLE_USER',
       'Isolated legacy account', '2026-11-09', owner
FROM (SELECT DISTINCT f.bId AS owner FROM legacy.FOODM f JOIN legacy.DISPOSALS d USING (foodMaterial_Id)) b
ORDER BY owner;
INSERT INTO itemdb.item (account_id, sku, name, unit_price, status, created_at, updated_at)
SELECT a.id, CONCAT('LEGACY:', f.foodMaterial_Id), f.foodMaterialName, f.foodMaterialPrice,
       'ACTIVE', '2026-11-09', '2026-11-09'
FROM legacy.FOODM f JOIN mydb.account a ON BINARY a.b_id = BINARY f.bId
WHERE EXISTS (SELECT 1 FROM legacy.DISPOSALS d WHERE d.foodMaterial_Id = f.foodMaterial_Id)
ORDER BY BINARY f.foodMaterial_Id;
INSERT INTO inventorydb.inventory (account_id, item_id, on_hand_quantity, created_at, updated_at)
SELECT i.account_id, i.id, f.totalWeight, '2026-11-09', '2026-11-09'
FROM itemdb.item i JOIN legacy.FOODM f ON BINARY i.sku = BINARY CONCAT('LEGACY:', f.foodMaterial_Id)
ORDER BY i.id;
INSERT INTO inventorydb.stock_movement (
    inventory_id, account_id, item_id, request_id, movement_type, quantity_delta,
    quantity_before, quantity_after, reason, created_at)
SELECT id, account_id, item_id, CONCAT('LEGACY-OPENING-', item_id), 'INITIAL',
       on_hand_quantity, 0, on_hand_quantity, 'Legacy snapshot opening balance', created_at
FROM inventorydb.inventory;
INSERT INTO disposalsdb.legacy_disposal_history
SELECT d.disposal_Id, f.bId, f.foodMaterial_Id, d.reason_Id, r.reason, d.disposalCountAll, d.disposalPrice,
       CAST(d.disposalDate AS CHAR), i.account_id, i.id
FROM legacy.DISPOSALS d JOIN legacy.FOODM f USING (foodMaterial_Id) JOIN legacy.REASON r USING (reason_Id)
JOIN itemdb.item i ON BINARY i.sku = BINARY CONCAT('LEGACY:', f.foodMaterial_Id)
JOIN mydb.account a ON a.id = i.account_id AND BINARY a.b_id = BINARY f.bId;
"""
LOCK_WAIT_SQL = """
SELECT waiting.THREAD_ID, blocker.THREAD_ID, waiting.INDEX_NAME
FROM performance_schema.data_lock_waits w
JOIN performance_schema.data_locks waiting ON waiting.ENGINE_LOCK_ID = w.REQUESTING_ENGINE_LOCK_ID
    AND waiting.ENGINE = w.ENGINE
JOIN performance_schema.data_locks blocker ON blocker.ENGINE_LOCK_ID = w.BLOCKING_ENGINE_LOCK_ID
    AND blocker.ENGINE = w.ENGINE
WHERE waiting.OBJECT_SCHEMA = 'disposalsdb' AND waiting.OBJECT_NAME = 'disposal'
  AND blocker.OBJECT_SCHEMA = 'disposalsdb' AND blocker.OBJECT_NAME = 'disposal'
  AND waiting.LOCK_TYPE = 'RECORD' AND waiting.LOCK_STATUS = 'WAITING';
"""
RETRY_GRANTS = f"""
GRANT UPDATE ON disposalsdb.disposal TO '{DB_USER}'@'%';
GRANT UPDATE ON inventorydb.inventory TO '{DB_USER}'@'%';
GRANT INSERT ON inventorydb.stock_movement TO '{DB_USER}'@'%';
SET GLOBAL read_only=OFF;
"""


def command(*args, input=None, env=None):
    result = subprocess.run(args, input=input, env=env, capture_output=True, timeout=45)
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).name} failed with exit {result.returncode}")
    return result.stdout


def digest(text):
    return sha256(text.encode()).hexdigest()


def json_lines(text):
    return [json.loads(line) for line in text.split("\n") if line]


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def request(port, path, method="GET", body=None, token=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(body).encode()
    with ExitStack() as stack:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=8)
        stack.callback(conn.close)
        conn.request(method, path, body, headers)
        response = stack.enter_context(conn.getresponse())
        payload = response.read()
    return response.status, json.loads(payload) if payload else {}


def read(port, path, token=None):
    status, result = request(port, path, token=token)
    assert status == 200, f"격리 조회 HTTP {status}"
    return result


def wait_for(description, check, process):
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline and process.poll() is None:
        try:
            if check():
                return
        except (OSError, http.client.HTTPException, cli.InvestigationError, ValueError):
            pass
        time.sleep(0.25)
    raise RuntimeError(f"{description} 준비 실패")


def stop_process(process):
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def start_process(stack, directory, name, args, env=None, stream=False):
    log = stack.enter_context((directory / f"{name}.log").open("w", encoding="utf-8"))
    process = subprocess.Popen(
        args, cwd=directory, env=env, encoding="utf-8", stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if stream else log, stderr=log, start_new_session=True,
    )
    stack.callback(stop_process, process)
    if stream:
        stack.callback(process.stdout.close)
    return process


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(stack, handler):
    server = stack.enter_context(ThreadingHTTPServer(("127.0.0.1", 0), handler))
    Thread(target=server.serve_forever, daemon=True).start()
    stack.callback(server.shutdown)
    return server.server_port


def start_database(stack, directory, mysql_bin):
    mysqld = mysql_bin / "mysqld"
    mysql = mysql_bin / "mysql"
    basedir = mysqld.resolve().parent.parent
    data = directory / "mysql"
    socket_path = directory / "db.sock"
    port = free_port()
    password = secrets.token_hex(24)
    options = directory / "mysql.cnf"
    options.touch(mode=0o600, exist_ok=False)
    options.write_text(f"[client]\nuser=root\npassword={password}\nsocket={socket_path}\n")
    init = directory / "mysql-init.sql"
    init.touch(mode=0o600, exist_ok=False)
    init.write_text(f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{password}';\n")
    command(mysqld, "--no-defaults", "--initialize-insecure", f"--basedir={basedir}", f"--datadir={data}")
    process = start_process(stack, directory, "db", [
        mysqld, "--no-defaults", f"--basedir={basedir}", f"--datadir={data}",
        f"--socket={socket_path}", f"--port={port}", f"--pid-file={directory / 'db.pid'}",
        f"--init-file={init}", "--bind-address=127.0.0.1", "--mysqlx=OFF", "--skip-log-bin",
        "--local-infile=OFF", "--secure-file-priv=NULL", "--performance-schema=ON",
        "--default-authentication-plugin=mysql_native_password",
    ])
    client = [
        mysql, f"--defaults-file={options}", "--protocol=SOCKET", f"--socket={socket_path}", "--user=root",
        "--batch", "--skip-column-names", "--raw", "--binary-mode", "--local-infile=0",
        "--default-character-set=utf8mb4",
    ]
    client_env = {**os.environ, "MYSQL_TEST_LOGIN_FILE": str(directory / "unused-login.cnf")}
    command(*client, "--version", env=client_env)
    wait_for("격리 MySQL", lambda: subprocess.run(
        [*client, "-e", "SELECT 1"], env=client_env, capture_output=True, timeout=3
    ).returncode == 0, process)
    init.unlink()

    def sql(statement):
        return command(*client, input=statement.encode(), env=client_env).decode()

    return port, sql


def extract_legacy_tables(backup):
    with gzip.open(backup, "rt", encoding="utf-8") as stream:
        dump = stream.read()
    statements = []
    for table in ("REASON", "FOODM", "DISPOSALS"):
        [schema] = re.findall(r"^CREATE TABLE `" + table + r"` \(\n.*?\n\) ENGINE[^\n]+;", dump, re.M | re.S)
        [rows] = re.findall(r"^INSERT INTO `" + table + r"` VALUES\n((?:\([^\n]+(?:,|;)\n)+)", dump, re.M)
        statements.extend((schema, f"INSERT INTO `{table}` VALUES\n{rows}"))
    return "\n".join(statements)


def restore_fixture(sql, legacy_tables, migration):
    sql("CREATE DATABASE legacy; CREATE DATABASE mydb; CREATE DATABASE itemdb; "
        "CREATE DATABASE inventorydb; CREATE DATABASE disposalsdb;")
    sql(f"USE legacy; SET FOREIGN_KEY_CHECKS=0;\n{legacy_tables}\nSET FOREIGN_KEY_CHECKS=1;")
    for schema, path in SCHEMAS:
        sql(f"USE {schema};\n" + (ROOT / path).read_text())
    sql(RESTORE_SQL)
    archive = json_lines(sql(ARCHIVE_SQL))
    assert len(archive) == migration["archiveRows"], "격리 복원 이력 건수가 이관 기록과 다릅니다."
    assert digest(json.dumps(archive, sort_keys=True, ensure_ascii=False, separators=(",", ":"))) == migration["archiveSha256"], (
        "격리 복원 이력 해시가 이관 기록과 다릅니다."
    )
    balances = [tuple(map(int, line.split())) for line in sql(
        "SELECT account_id, item_id, on_hand_quantity FROM inventorydb.inventory ORDER BY item_id;"
    ).splitlines()]
    assert len(balances) == migration["stock"]["inventoryRows"], "격리 복원 재고 건수가 이관 기록과 다릅니다."
    selected = next((row for row in balances if row[2] > 0), None)
    assert selected is not None, "폐기 검증에 사용할 양수 재고가 없습니다."
    return selected


def make_token(directory, account):
    command(ROOT / "scripts/generate-jwt-keys.sh", ISSUER, directory / "keys")

    def encode(data):
        return base64.urlsafe_b64encode(data).rstrip(b"=")

    now = int(time.time())
    fields = [
        {"alg": "RS256", "typ": "JWT", "kid": ISSUER},
        {"iss": ISSUER, "aud": ISSUER, "sub": str(account), "iat": now, "exp": now + 900,
         "token_type": "access", "email": "fixture@example.invalid", "role": "ROLE_USER"},
    ]
    message = b".".join(encode(json.dumps(field).encode()) for field in fields)
    signature = command("openssl", "dgst", "-sha256", "-sign", directory / "keys/private" / f"{ISSUER}.pem", input=message)
    return (message + b"." + encode(signature)).decode()


def stock_proxy(stack, food_port, path, token, lose_response):
    calls = []
    sequence = Lock()
    held, release = Event(), Event()

    class StockProxy(Handler):
        def do_POST(self):
            if self.path != path or self.headers.get("Authorization") != f"Bearer {token}":
                return self.reply(403, {})
            if self.headers.get("Transfer-Encoding") == "chunked":
                chunks = []
                while size := int(self.rfile.readline().split(b";", 1)[0], 16):
                    chunks.append(self.rfile.read(size))
                    assert self.rfile.read(2) == b"\r\n"
                body = json.loads(b"".join(chunks))
            else:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with sequence:
                first = not calls
                if not first:
                    assert body == calls[0]["body"], "재시도 재고 명령이 최초 요청과 다릅니다."
                hold = len(calls) == 1
                entry = {"body": body, "forwarded": not first or lose_response}
                calls.append(entry)
            if entry["forwarded"]:
                status, result = request(food_port, path, "POST", body, token)
                entry.update(status=status, movementId=result.get("movementId"))
            if first:
                self.close_connection = True
                return
            if hold:
                held.set()
                release.wait(2.2)
            self.reply(status, result)

    return serve(stack, StockProxy), calls, held, release


def start_services(stack, directory, options, ports, db_port, password, proxy):
    common = {
        "PATH": os.environ.get("PATH", os.defpath), "LANG": "en_US.UTF-8",
        "JWT_ISSUER": ISSUER, "JWT_AUDIENCE": ISSUER,
        "JWT_PUBLIC_KEY_DIRECTORY": str(directory / "keys/public"), "SERVER_ADDRESS": "127.0.0.1",
        "EUREKA_CLIENT_ENABLED": "false", "SPRING_CLOUD_DISCOVERY_ENABLED": "false",
        "FOOD_MATERIAL_DISCOVERY_ENABLED": "false", "FOOD_MATERIAL_SERVICE_BASE_URL": f"http://127.0.0.1:{proxy}",
        "SPRING_FLYWAY_ENABLED": "false", "FOOD_MATERIAL_INVENTORY_FLYWAY_BASELINE_ON_MIGRATE": "true",
    }
    for prefix, schema in (("FOOD_MATERIAL", "itemdb"), ("FOOD_MATERIAL_INVENTORY", "inventorydb"), ("DISPOSALS", "disposalsdb")):
        common.update({
            f"{prefix}_DB_URL": f"jdbc:mariadb://127.0.0.1:{db_port}/{schema}",
            f"{prefix}_DB_USERNAME": DB_USER,
            f"{prefix}_DB_PASSWORD": password,
        })
    running = {}
    for job, (module, prefix) in SERVICES.items():
        env = {**common, f"{prefix}_SERVER_PORT": str(ports[job])}
        if job == "gateway-server":
            routes = [
                {"id": name, "uri": f"http://127.0.0.1:{ports[target]}", "predicates": [f"Path=/{name}/**"]}
                for name, target in (("foodmaterials", "foodmaterials-service"), ("disposals", "disposals-service"))
            ]
            env["SPRING_APPLICATION_JSON"] = json.dumps({"spring.cloud.gateway.server.webmvc.routes": routes})
        running[job] = start_process(stack, directory, job, [options.java, "-Xmx320m", "-jar", options.jars[module]], env)
    for job, process in running.items():
        wait_for(job, lambda: request(ports[job], "/actuator/health")[0] == 200, process)

    config = directory / "prometheus.yml"
    config.write_text("global:\n  scrape_interval: 2s\n  scrape_timeout: 1s\nscrape_configs:\n" + "".join(
        f'  - job_name: {job}\n    metrics_path: /actuator/prometheus\n    static_configs:\n'
        f'      - targets: ["127.0.0.1:{port}"]\n' for job, port in ports.items()
    ))
    port = free_port()
    prom = start_process(stack, directory, "prometheus", [
        options.prometheus, f"--config.file={config}", f"--storage.tsdb.path={directory / 'tsdb'}",
        f"--web.listen-address=127.0.0.1:{port}",
    ])

    def targets_up():
        status, data = request(port, "/api/v1/query?query=up")
        return status == 200 and {
            row["metric"]["job"] for row in data["data"]["result"] if row["value"][1] == "1"
        } == set(ports)

    wait_for("격리 Prometheus", targets_up, prom)
    return port


def read_proxies(stack, gateway, prometheus, token, paths, ready, erp_calls, prom_calls):
    class ERPReads(Handler):
        def do_GET(self):
            if self.path not in paths or self.headers.get("Authorization") != f"Bearer {token}" or not ready.wait(5):
                return self.reply(403, {})
            erp_calls.append({"method": "GET", "source": paths[self.path]})
            self.reply(*request(gateway, self.path, token=token))

    class PromReads(Handler):
        def do_GET(self):
            if not self.path.startswith("/api/v1/query?") or self.headers.get("Authorization"):
                return self.reply(403, {})
            args = parse_qs(urlsplit(self.path).query)
            metrics = [name for name, query in QUERIES.items() if args.get("query") == [query]]
            if len(metrics) != 1 or len(args.get("time", [])) != 1:
                return self.reply(403, {})
            prom_calls.append({"method": "GET", "metric": metrics[0], "time": float(args["time"][0])})
            self.reply(*request(prometheus, self.path))

    return serve(stack, ERPReads), serve(stack, PromReads)


def agent_child(role, audit_file, args):
    """Trace the normal CLI entry points without changing their tool permissions."""
    from serve_disposal_metrics import main as serve_metrics

    def record(kind, **fields):
        with audit_file.open("a", encoding="utf-8") as audit:
            audit.write(json.dumps({"kind": kind, "role": role, **fields}) + "\n")

    execute, run_scope, send = cli.execute_opencode, cli.run_scoped_agent, MetricsA2AClient.request

    def trace_tools(*args, **kwargs):
        result = execute(*args, **kwargs)
        events = json_lines("\n".join(line for line in result.stdout.splitlines() if line.startswith("{")))
        tools = [
            {"name": event["part"]["tool"], "status": event["part"]["state"]["status"]}
            for event in events if event.get("type") == "tool_use"
        ]
        record("modelTools", tools=tools)
        return result

    def trace_decision(*args, **kwargs):
        output = run_scope(*args, **kwargs)
        with suppress(ValueError):
            record("modelDecision", decision=json.loads(output))
        return output

    def trace_a2a(client, method, path, payload=None):
        response = send(client, method, path, payload)
        task = response.get("task", response)
        if path == "/message:send":
            message = payload["message"]
            record("submit", referenceTaskIds=message.get("referenceTaskIds"), contextId=message.get("contextId"),
                   assignedContextId=task.get("contextId"), taskId=task.get("id"), data=message["parts"][0]["data"])
        if task.get("status", {}).get("state") == "TASK_STATE_COMPLETED":
            record("complete", taskId=task["id"], contextId=task["contextId"],
                   artifact=task["artifacts"][0]["parts"][0]["data"])
        return response

    sys.argv = [sys.argv[0], *args]
    with patch.object(cli, "execute_opencode", trace_tools), patch.object(
        cli, "run_scoped_agent", trace_decision
    ), patch.object(MetricsA2AClient, "request", trace_a2a):
        return serve_metrics() if role == "metrics" else cli.main()


def concurrent_retry(sql, gateway, path, token, held, release):
    barrier = Barrier(3)
    origin = time.monotonic_ns()

    def retry(number):
        barrier.wait(4)
        start = time.monotonic_ns()
        http, response = request(gateway, path, "POST", token=token)
        end = time.monotonic_ns()
        return {
            "number": number, "http": http, "response": response,
            "startMs": (start - origin) / 1e6, "endMs": (end - origin) / 1e6,
        }

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(retry, number) for number in (1, 2)]
        try:
            barrier.wait(4)
            assert held.wait(3), "재시도가 격리 재고 서비스에 도달하지 않았습니다."
            deadline = time.monotonic() + 1.65
            waits = []
            while time.monotonic() < deadline:
                waits = [row.split("\t") for row in sql(LOCK_WAIT_SQL).splitlines()]
                if waits:
                    break
                time.sleep(0.025)
        finally:
            release.set()
        results = [future.result(timeout=10) for future in futures]

    assert waits and all(waiter != blocker and index == "PRIMARY" for waiter, blocker, index in waits), (
        "격리 DB에서 폐기 행 잠금 대기를 관측하지 못했습니다."
    )
    overlap = min(row["endMs"] for row in results) - max(row["startMs"] for row in results)
    assert overlap > 0, "두 재시도 요청이 겹치지 않았습니다."
    return results, overlap, [
        {"waiterThread": int(waiter), "blockerThread": int(blocker), "index": index}
        for waiter, blocker, index in waits
    ]


def lock_database(sql):
    sql(f"""
SET GLOBAL read_only=ON;
REVOKE ALL PRIVILEGES, GRANT OPTION FROM '{DB_USER}'@'%';
GRANT SELECT ON itemdb.* TO '{DB_USER}'@'%';
GRANT SELECT ON inventorydb.* TO '{DB_USER}'@'%';
GRANT SELECT ON disposalsdb.* TO '{DB_USER}'@'%';
""")
    assert sql("SELECT @@global.read_only;").strip() == "1", "격리 DB가 읽기 전용이 아닙니다."
    grants = sql(f"SHOW GRANTS FOR '{DB_USER}'@'%';").splitlines()
    assert len(grants) == 4 and all(line.startswith(("GRANT USAGE ON ", "GRANT SELECT ON ")) for line in grants), (
        "에이전트 조회 시 격리 서비스 계정의 권한이 예상과 다릅니다."
    )


def audit_agents(audit, erp_calls, prom_calls, initial_conclusion, private_values):
    events = json_lines(audit.read_text())
    submissions = [event for event in events if event["kind"] == "submit"]
    completed = [event for event in events if event["kind"] == "complete"]
    assert len(submissions) == len(completed) == 2, "두 A2A 단계의 완료를 확인하지 못했습니다."
    before, after = submissions
    assert [entry["data"]["status"] for entry in submissions] == ["PENDING", "COMPLETED"]
    assert after["taskId"] != before["taskId"] and after["contextId"] == before["assignedContextId"] == after["assignedContextId"]
    assert after["referenceTaskIds"] == [before["taskId"]], "완료 태스크가 초기 태스크를 참조하지 않습니다."
    comparison = {"inventory": True, "ledger": True}
    assert before["data"]["disposalConclusion"] == initial_conclusion
    assert after["data"]["stockComparison"] == comparison
    for submitted, returned in zip(submissions, completed):
        assert submitted["taskId"] == returned["taskId"] and submitted["assignedContextId"] == returned["contextId"]
    verdict = completed[-1]["artifact"]["decision"]
    assert verdict["previousDisposalConclusion"] == initial_conclusion and verdict["disposalConclusion"] == "matched"
    assert verdict["stockComparison"] == comparison
    assert not any(secret in json.dumps(submissions) for secret in private_values), "A2A 요청에 비공개 값이 포함됐습니다."
    for role, expected in (
        ("disposal", {"erp_get_disposal", "erp_get_stock_snapshot", "erp_delegate_prometheus"}),
        ("metrics", {"erp_get_service_metric"}),
    ):
        role_events = [event for event in events if event["role"] == role]
        groups = [event["tools"] for event in role_events if event["kind"] == "modelTools"]
        decisions = [event for event in role_events if event["kind"] == "modelDecision"]
        assert len(decisions) == len(groups) == 2, f"{role} 실제 모델의 양쪽 실행 증거가 부족합니다."
        assert all(len(group) == 3 and {tool["name"] for tool in group} == expected and
                   all(tool["status"] == "completed" for tool in group) for group in groups)
    assert len(prom_calls) == 6
    for index, phase in enumerate(submissions):
        queries = prom_calls[index * 3:(index + 1) * 3]
        assert {query["metric"] for query in queries} == set(QUERIES)
        assert {query["time"] for query in queries} == {phase["data"]["windowEnd"]}
    assert all(call["method"] == "GET" for call in erp_calls + prom_calls)
    return {
        "erpReads": erp_calls, "prometheusReads": prom_calls, "a2aSubmissions": submissions, "a2aCompleted": completed,
        "modelEvents": [event for event in events if event["kind"] in ("modelTools", "modelDecision")],
    }


def run_scenario(name, options, legacy_tables, migration):
    lose_response = name == "lost-stock-response"
    with tempfile.TemporaryDirectory(prefix="erpmsa-retry-", dir="/tmp") as raw, ExitStack() as stack:
        directory = Path(raw).resolve()
        db_port, sql = start_database(stack, directory, options.mysql_bin_dir)
        account, item, opening = restore_fixture(sql, legacy_tables, migration)
        initial_stock = digest(sql(STOCK_SQL))
        archive = digest(sql(ARCHIVE_SQL))
        password = secrets.token_hex(24)
        sql(f"""
CREATE USER '{DB_USER}'@'%' IDENTIFIED BY '{password}';
GRANT ALL ON itemdb.* TO '{DB_USER}'@'%';
GRANT ALL ON inventorydb.* TO '{DB_USER}'@'%';
GRANT ALL ON disposalsdb.* TO '{DB_USER}'@'%';
""")
        token = make_token(directory, account)
        ports = {job: free_port() for job in SERVICES}
        assert len(set(ports.values())) == len(ports), "격리 서비스 포트가 겹칩니다."
        gateway = ports["gateway-server"]
        inventory_path = f"/foodmaterials/inventories/{item}"
        ledger_path = inventory_path + "/movements?page=0&size=100"
        proxy, stock_calls, held, release = stock_proxy(
            stack, ports["foodmaterials-service"], inventory_path + "/disposals", token, lose_response
        )
        prometheus = start_services(stack, directory, options, ports, db_port, password, proxy)
        assert digest(sql(STOCK_SQL)) == initial_stock, "서비스 기동 중 재고 또는 원장이 바뀌었습니다."
        for _ in range(3):
            read(gateway, inventory_path, token)
            read(gateway, "/disposals?status=PENDING&page=0&size=1", token)
            time.sleep(2.1)

        http, pending = request(gateway, "/disposals", "POST", {
            "requestId": "CONCURRENT-RETRY-VERIFICATION", "foodMaterialId": item,
            "quantity": 1, "reason": "격리 동시 재시도 검증",
        }, token)
        assert http == 202 and pending["status"] == "PENDING" and pending["movementId"] is None
        assert len(stock_calls) == 1 and stock_calls[0]["forwarded"] == lose_response
        disposal_id = pending["disposalId"]
        detail_path = f"/disposals/{disposal_id}"
        assert stock_calls[0]["body"]["requestId"] == f"DISPOSAL-{disposal_id}"
        inventory_before = read(gateway, inventory_path, token)
        ledger_before = read(gateway, ledger_path, token)["movements"]
        deductions = [row for row in ledger_before if row["movementType"] == "DISPOSAL"]
        initial_movement = None
        if lose_response:
            [initial_movement] = deductions
            assert stock_calls[0]["status"] == 200 and stock_calls[0]["movementId"] == initial_movement["movementId"]
            assert inventory_before["onHandQuantity"] == opening - 1
            assert (initial_movement["quantityBefore"], initial_movement["quantityDelta"],
                    initial_movement["quantityAfter"]) == (opening, -1, opening - 1)
        else:
            assert not deductions and inventory_before["onHandQuantity"] == opening
            assert digest(sql(STOCK_SQL)) == initial_stock

        time.sleep(2.2)
        lock_database(sql)
        before = digest(sql(STABLE_SQL))
        before_stock = digest(sql(STOCK_SQL))
        print(f"[{name}] 202 PENDING, 재고 {inventory_before['onHandQuantity']}, 차감 원장 {len(deductions)}건", flush=True)

        ready = Event()
        ready.set()
        erp_calls, prom_calls = [], []
        erp_port, metrics_port = read_proxies(
            stack, gateway, prometheus, token,
            {detail_path: "disposal-detail", inventory_path: "current-stock", ledger_path: "stock-ledger"},
            ready, erp_calls, prom_calls,
        )
        audit = directory / "audit.jsonl"
        audit.touch(mode=0o600)
        a2a_port = free_port()
        a2a_token = secrets.token_urlsafe(32)
        env = {**os.environ, A2A_TOKEN_ENV: a2a_token, "PYTHONUNBUFFERED": "1"}
        env.pop(cli.TOKEN_ENV, None)
        child = [sys.executable, str(Path(__file__).resolve()), "--agent-child"]
        peer = start_process(stack, directory, "a2a", [
            *child, "metrics", str(audit), "--port", str(a2a_port),
            "--prometheus-port", str(metrics_port), "--model", options.model,
        ], env)
        wait_for("격리 A2A", lambda: MetricsA2AClient(a2a_port, a2a_token).request("GET", CARD_PATH), peer)
        lead = start_process(stack, directory, "lead", [
            *child, "disposal", str(audit), disposal_id, "--port", str(erp_port),
            "--a2a-port", str(a2a_port), "--follow-retry", "30", "--model", options.model,
        ], {**env, cli.TOKEN_ENV: token}, stream=True)

        retry = None
        output = []
        for line in lead.stdout:
            output.append(line.strip())
            if not line.startswith("재시도 대기 |"):
                continue
            assert retry is None and digest(sql(STABLE_SQL)) == before, "초기 조사 중 격리 DB가 바뀌었습니다."
            ready.clear()
            try:
                sql(RETRY_GRANTS)
                retry = concurrent_retry(sql, gateway, detail_path + "/retry", token, held, release)
            finally:
                lock_database(sql)
                ready.set()
            after = digest(sql(STABLE_SQL))
            print(f"[{name}] 동시 재시도 응답 {[row['http'] for row in retry[0]]}, 폐기 행 잠금 대기 확인", flush=True)

        if lead.wait(timeout=5) != 0:
            raise RuntimeError("A2A 조회 실패 | " + " / ".join(output[-3:]))
        assert retry is not None and digest(sql(STABLE_SQL)) == after, "완료 조사 중 격리 DB가 바뀌었습니다."
        results, overlap, waits = retry
        inventory_after = read(gateway, inventory_path, token)
        ledger_after = read(gateway, ledger_path, token)["movements"]
        [movement] = [row for row in ledger_after if row["movementType"] == "DISPOSAL"]
        after_stock = digest(sql(STOCK_SQL))
        assert sql("SELECT COUNT(*) FROM disposalsdb.disposal WHERE status='COMPLETED';").strip() == "1"
        assert sql("SELECT COUNT(*) FROM inventorydb.stock_movement WHERE movement_type='DISPOSAL';").strip() == "1"
        assert digest(sql(ARCHIVE_SQL)) == archive and sql("SELECT @@global.read_only;").strip() == "1"
        assert inventory_after["onHandQuantity"] == opening - 1
        assert (movement["quantityBefore"], movement["quantityDelta"], movement["quantityAfter"]) == (opening, -1, opening - 1)
        assert movement["requestId"] == f"DISPOSAL-{disposal_id}"
        assert len(stock_calls) == 2 and stock_calls[1]["forwarded"] and stock_calls[1]["status"] == 200
        assert stock_calls[0]["body"] == stock_calls[1]["body"] and stock_calls[1]["movementId"] == movement["movementId"]
        if initial_movement:
            assert movement == initial_movement and ledger_after == ledger_before
            assert inventory_after == inventory_before and after_stock == before_stock
        else:
            assert inventory_after["version"] == inventory_before["version"] + 1
            assert [row for row in ledger_after if row != movement] == ledger_before

        for result in results:
            response = result.pop("response")
            assert result["http"] == 200 and response["status"] == "COMPLETED"
            assert response["disposalId"] == disposal_id and response["requestId"] == pending["requestId"]
            assert response["movementId"] == movement["movementId"] and response["quantityAfter"] == opening - 1
            result.update(status=response["status"], movementId=response["movementId"], quantityAfter=response["quantityAfter"])

        agents = audit_agents(audit, erp_calls, prom_calls, "matched" if lose_response else "no_match",
                              (token, a2a_token, disposal_id))
        result = {
            "scenario": name, "status": "PASS", "pendingHttp": http, "firstStockRequestForwarded": lose_response,
            "retry": {"responses": results, "overlapMs": overlap, "disposalRowLockWaits": waits,
                      "stockRequestsForwardedOnRetry": 1},
            "stock": {"opening": opening, "beforeRetry": inventory_before["onHandQuantity"],
                      "afterRetry": inventory_after["onHandQuantity"], "versionBefore": inventory_before["version"],
                      "versionAfter": inventory_after["version"], "disposalMovementsBefore": len(deductions),
                      "disposalMovementsAfter": 1, "initialMovementId": stock_calls[0].get("movementId"),
                      "snapshotSha256BeforeRetry": before_stock, "snapshotSha256AfterRetry": after_stock},
            "agentDbReadOnly": True, **agents, "summary": output[-2:],
        }
    result["temporaryRuntimeRemoved"] = True
    return result


def parse_options():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", required=True, type=Path, help="이관 검증에 사용한 레거시 SQL gzip")
    parser.add_argument("--migration-report", required=True, type=Path, help="백업과 이력 SHA-256을 담은 이관 검증 JSON")
    parser.add_argument("--mysql-bin-dir", type=Path, default=Path("/usr/local/mysql/bin"), help="MySQL 8.0 mysql·mysqld 경로")
    parser.add_argument("--prometheus", default="prometheus", help="Prometheus 실행 파일 또는 PATH 이름")
    parser.add_argument("--java", help="Java 21 실행 파일 또는 PATH 이름")
    parser.add_argument("--model", default="opencode/gpt-5.4-nano", help="두 에이전트에 사용할 실제 OpenCode 모델")
    parser.add_argument("--report", required=True, type=Path, help="새 결과 JSON 경로")
    options = parser.parse_args()
    if not __debug__:
        parser.error("검증 조건을 유지하려면 Python 최적화 모드를 해제하세요.")
    if options.report.exists() or options.report.is_symlink():
        parser.error("--report에는 새 파일 경로를 지정하세요.")
    if not re.fullmatch(r"[\w.-]+/[\w./:#-]+", options.model):
        parser.error("--model은 OpenCode의 provider/model 형식이어야 합니다.")
    options.mysql_bin_dir = options.mysql_bin_dir.resolve()
    if not options.java and Path("/usr/libexec/java_home").exists():
        options.java = str(Path(command("/usr/libexec/java_home", "-v", "21").decode().strip()) / "bin/java")
    options.java = shutil.which(options.java or "java")
    options.prometheus = shutil.which(options.prometheus)
    executables = (options.java, options.prometheus, options.mysql_bin_dir / "mysql",
                   options.mysql_bin_dir / "mysqld", "openssl", "opencode")
    if not all(executable and shutil.which(executable) for executable in executables):
        parser.error("Java 21, MySQL 8.0 클라이언트·서버, Prometheus, OpenSSL, OpenCode 실행 파일을 확인하세요.")
    options.java = Path(options.java).resolve()
    options.prometheus = Path(options.prometheus).resolve()
    options.jars = {}
    for module, _prefix in SERVICES.values():
        jars = [path for path in (ROOT / module / "build/libs").glob("*.jar") if not path.name.endswith("-plain.jar")]
        if len(jars) != 1:
            parser.error(f"{module} bootJar가 한 개 필요합니다.")
        options.jars[module] = jars[0]
    return options


def main():
    if sys.argv[1:2] == ["--agent-child"]:
        role, audit, *args = sys.argv[2:]
        return agent_child(role, Path(audit), args)

    options = parse_options()
    migration = json.loads(options.migration_report.read_text())
    backup_hash = sha256(options.backup.read_bytes()).hexdigest()
    if migration.get("status") != "PASS" or migration["source"]["compressedBackupSha256"] != backup_hash:
        raise SystemExit("이관 검증 기록과 백업 SHA-256이 일치해야 합니다.")
    legacy_tables = extract_legacy_tables(options.backup)
    results = []
    for name in SCENARIOS:
        try:
            case = run_scenario(name, options, legacy_tables, migration)
        except (AssertionError, RuntimeError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            origin = traceback.extract_tb(error.__traceback__)[-1]
            case = {"scenario": name, "status": "FAIL",
                    "error": str(error) or f"{type(error).__name__} ({origin.name}:{origin.lineno})"}
        results.append(case)
        print(f"[{name}] {case['status']}" + (f" | {case['error']}" if "error" in case else ""), flush=True)
    backup_unchanged = sha256(options.backup.read_bytes()).hexdigest() == backup_hash
    passed = backup_unchanged and all(case["status"] == "PASS" for case in results)
    report = {
        "status": "PASS" if passed else "FAIL", "checkedAt": datetime.now(timezone.utc).isoformat(),
        "model": options.model, "sourceBackupSha256": backup_hash, "sourceArchiveSha256": migration["archiveSha256"],
        "sourceArchiveRows": migration["archiveRows"], "backupUnchanged": backup_unchanged, "scenarios": results,
    }
    options.report.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(options.report, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"{report['status']} | {options.report.resolve()}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
