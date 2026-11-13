import http.client
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import investigate_disposal as cli
from disposal_metrics import JOBS, QUERIES
from disposal_mcp import MCP_TOKEN_ENV


CLI = Path(__file__).with_name("investigate_disposal.py")
DISPOSAL_ID = "12345678-1234-4234-8234-123456789abc"
TOKEN = "test.header.signature"
REASON = "비공개 폐기 사유"
DETAIL = f"/disposals/{DISPOSAL_ID}"
LEDGER = "/foodmaterials/inventories/7/movements"
CREATED_AT = "2026-01-01T00:00:00Z"


def disposal(**overrides):
    return {
        "disposalId": DISPOSAL_ID, "foodMaterialId": 7, "status": "PENDING",
        "requestId": "user-input-request-id", "quantity": 3, "reason": REASON,
        "createdAt": CREATED_AT, **overrides,
    }


def movement(**overrides):
    return {
        "movementId": 9, "foodMaterialId": 7, "requestId": f"DISPOSAL-{DISPOSAL_ID}",
        "movementType": "DISPOSAL", "quantityBefore": 20, "quantityAfter": 17,
        "quantityDelta": -3, "reason": REASON, **overrides,
    }


def ledger(rows, page=0, total=None):
    total = len(rows) if total is None else total
    return {
        "movements": rows, "page": page, "size": 100,
        "totalElements": total, "totalPages": (total + 99) // 100,
    }


class DisposalCliTest(unittest.TestCase):
    def setUp(self):
        self.routes = {DETAIL: (200, disposal())}
        self.calls = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def reply(self):
                fixture.calls.append((self.command, self.path, self.headers.get("Authorization")))
                status, body = fixture.routes.get(self.path, (500, {}))
                payload = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Location", "/must-not-follow")
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PUT = do_DELETE = reply

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(self.server.shutdown)
        self.fake_dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.agent_log = self.fake_dir / "agent.json"
        program = self.fake_dir / "opencode"
        program.write_text(f"#!{sys.executable}\n" + FAKE_AGENT, encoding="utf-8")
        program.chmod(0o700)

    def set_page(self, page, body, status=200):
        self.routes[f"{LEDGER}?page={page}&size=100"] = status, body

    def set_metrics(self, *, empty=False, anchor=CREATED_AT):
        end = datetime.fromisoformat(anchor).timestamp() + 120
        samples = {"scrape": (1, 1, 0), "http_5xx": (0, 0, 2), "p95_seconds": (.2, .3, .5)}
        for metric, query in QUERIES.items():
            path = "/api/v1/query?" + urlencode({"query": query, "time": end, "timeout": "2s"})
            rows = [{"metric": {"job": job}, "value": [end, str(value)]}
                    for job, value in zip(JOBS, samples[metric])]
            self.routes[path] = 200, {"status": "success", "data": {"resultType": "vector", "result": [] if empty else rows}}

    def invoke(self, *options, disposal_id=DISPOSAL_ID, token=TOKEN, mode="auto", live=False):
        env = {
            **os.environ, "ERPMSA_ACCESS_TOKEN": token,
            "FAKE_AI_LOG": str(self.agent_log), "FAKE_AI_MODE": mode,
        }
        if not live:
            env["PATH"] = str(self.fake_dir) + os.pathsep + os.environ.get("PATH", "")
        result = subprocess.run(
            [sys.executable, str(CLI), disposal_id, "--port", str(self.server.server_port), *options],
            env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=285 if live else 10,
        )
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
        self.assertNotIn(REASON, result.stdout + result.stderr)
        for method, path, auth in self.calls:
            self.assertEqual("GET", method)
            self.assertEqual(None if path.startswith("/api/v1/query?") else f"Bearer {TOKEN}", auth)
        return result

    def assert_inconclusive(self, result, evidence):
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("판정 | 확인 불가", result.stdout)
        self.assertIn(evidence, result.stdout)
        self.assertNotIn("/retry", result.stdout)

    def test_agent_selects_tools_and_confirms_deduction(self):
        self.set_page(0, ledger([movement()]))
        result = self.invoke("--model", "opencode/test-model")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("movementId=9", result.stdout)
        self.assertIn("20 → 17 (-3)", result.stdout)
        self.assertIn(f"POST {DETAIL}/retry", result.stdout)
        self.assertEqual(2, len(self.calls))
        record = json.loads(self.agent_log.read_text())
        self.assertFalse(record["token_in_env"])
        self.assertEqual(["get_disposal", "get_stock_movements"], record["tools"])
        self.assertTrue(Path(record["cwd"]).name.startswith("erpmsa-opencode-"))
        rules = record["config"]["agents"][cli.AGENT]["permissions"]
        self.assertEqual(f"Bearer {{env:{MCP_TOKEN_ENV}}}",
                         record["config"]["mcp"]["servers"]["erp"]["headers"]["Authorization"])
        self.assertEqual({"action": "*", "resource": "*", "effect": "deny"}, rules[0])
        self.assertEqual({"erp_get_disposal", "erp_get_stock_movements"}, {rule["action"] for rule in rules[1:]})
        for sensitive in (TOKEN, REASON, DISPOSAL_ID, "user-input-request-id"):
            self.assertNotIn(sensitive, json.dumps(record["tool_results"], ensure_ascii=False))

    def test_agent_chooses_later_pages_using_internal_key(self):
        first = [movement(movementId=100 + i, requestId=f"other-{i}") for i in range(100)]
        first[0]["requestId"] = "user-input-request-id"
        self.set_page(0, ledger(first, total=101))
        self.set_page(1, ledger([movement()], page=1, total=101))
        result = self.invoke()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("movementId=9", result.stdout)
        self.assertIn("원장 2페이지 조회", result.stdout)
        self.assertEqual(3, len(self.calls))

    def test_no_match_and_empty_ledger_preserve_uncertainty(self):
        for rows, count in (([], 0), ([movement(requestId="INITIAL:7")], 1)):
            with self.subTest(count=count):
                self.set_page(0, ledger(rows))
                result = self.invoke()
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn(f"원장 {count}건에서 해당 키를 찾지 못했습니다", result.stdout)
                self.assertIn("차감 여부는 미확정", result.stdout)

    def test_conflicting_movement_fails_closed(self):
        for fields in ({"movementType": "ADJUSTMENT"}, {"quantityDelta": -4}, {"reason": "다른 사유"},
                       {"quantityAfter": 18}, {"foodMaterialId": 8}):
            with self.subTest(fields=fields):
                self.set_page(0, ledger([movement(**fields)]))
                self.assert_inconclusive(self.invoke(), "대조에 실패했습니다")

    def test_agent_stops_for_completed_and_rejected_disposals(self):
        for status in ("COMPLETED", "REJECTED"):
            with self.subTest(status=status):
                self.calls.clear()
                self.routes[DETAIL] = 200, disposal(status=status)
                result = self.invoke()
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("조사 대상 아님", result.stdout)
                self.assertEqual(1, len(self.calls))

    def test_page_limit_failure_and_concurrent_changes_are_inconclusive(self):
        first = [movement(movementId=100 + i, requestId=f"other-{i}") for i in range(100)]
        self.set_page(0, ledger(first, total=101))
        self.assert_inconclusive(self.invoke("--max-pages", "1"), "2페이지 중 1페이지만 확인")
        self.set_page(1, {}, status=503)
        self.assert_inconclusive(self.invoke(), "원장 2페이지 조회 실패 (HTTP 503)")
        self.set_page(1, ledger([movement()], page=1, total=102))
        self.assert_inconclusive(self.invoke(), "페이지 정보와 응답 건수가 일치하지 않습니다")
        self.set_page(1, ledger([movement(), movement(movementId=10)], page=1, total=102))
        self.assert_inconclusive(self.invoke(), "원장 건수가 바뀌었습니다")
        self.set_page(1, ledger([first[-1]], page=1, total=101))
        self.assert_inconclusive(self.invoke(), "중복으로 반환됐습니다")

    def test_inaccessible_disposal_and_redirect_stop_erp_requests(self):
        for status in (401, 403, 404, 302):
            with self.subTest(status=status):
                self.calls.clear()
                self.routes[DETAIL] = status, {"message": TOKEN}
                self.assert_inconclusive(self.invoke(), f"HTTP {status}")
                self.assertEqual(1, len(self.calls))

    def test_malformed_response_does_not_echo_body(self):
        self.set_page(0, f"<html>{TOKEN} {REASON}</html>".encode())
        self.assert_inconclusive(self.invoke(), "JSON으로 해석할 수 없습니다")

    def test_invalid_inputs_make_no_http_requests(self):
        self.assertEqual(2, self.invoke(disposal_id="../disposals").returncode)
        self.assert_inconclusive(self.invoke(token=""), "Access Token을 입력")
        self.assertEqual([], self.calls)

    def test_agent_cannot_override_scope_or_invoke_writes(self):
        for mode in ("write_tool", "override_id", "override_material", "before_detail", "skip_page"):
            with self.subTest(mode=mode):
                self.calls.clear()
                self.assert_inconclusive(self.invoke(mode=mode), "확인 불가")
                self.assertLessEqual(len(self.calls), 1)

    def test_unknown_mcp_method_and_wrong_capability_do_not_reach_erp(self):
        self.assert_inconclusive(self.invoke(mode="wrong_capability"), "근거")
        self.assertEqual([], self.calls)
        self.assert_inconclusive(self.invoke(mode="unknown_method"), "근거")
        self.assertEqual([], self.calls)

    def test_model_claims_require_observed_evidence(self):
        self.set_page(0, ledger([movement()]))
        for mode in ("no_tools", "early_finish", "wrong_conclusion", "invented_evidence"):
            with self.subTest(mode=mode):
                clue = "원장 조회를 완료하지 못했습니다" if mode == "early_finish" else "실제 조회 결과와 일치하지 않습니다"
                self.assert_inconclusive(self.invoke(mode=mode), clue)

    def test_repeated_calls_hit_budget_without_repeating_erp_writes(self):
        self.assert_inconclusive(self.invoke(mode="repeat"), "호출 한도")
        self.assertEqual(1, len(self.calls))

    def test_provider_error_stops_before_erp(self):
        self.assert_inconclusive(self.invoke(mode="auth_error"), "공급자 인증이 거절됐습니다")
        self.assertEqual([], self.calls)

    def test_provider_quota_is_distinguished_from_authentication(self):
        self.assert_inconclusive(self.invoke(mode="quota_error"), "모델 사용량 또는 잔액 한도")
        self.assertEqual([], self.calls)

    def test_metrics_agent_uses_validated_disposal_handoff_and_own_tools(self):
        self.set_page(0, ledger([movement()]))
        self.set_metrics()
        result = self.invoke("--prometheus-port", str(self.server.server_port))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(5, len(self.calls))
        self.assertIn("폐기 에이전트의 E1, E2 인계 확인", result.stdout)
        self.assertIn("차감 결과 응답부터 폐기 상태 확정", result.stdout)
        record = json.loads(self.agent_log.with_suffix(".metrics.json").read_text())
        self.assertEqual({"status": "PENDING", "disposalConclusion": "matched", "disposalEvidence": ["E1", "E2"]},
                         record["handoff"])
        self.assertFalse(record["token_in_env"])
        self.assertEqual(["get_service_metric"], record["catalog"])
        self.assertEqual({"erp_get_service_metric"}, {rule["action"] for rule in record["permissions"][1:]})
        self.assertEqual({"*"}, {record["permissions"][0]["action"]})

    def test_metrics_agent_cannot_query_other_tools_or_supply_promql(self):
        self.set_page(0, ledger([movement()]))
        for mode in ("metrics_scope_escape", "metrics_custom_query"):
            with self.subTest(mode=mode):
                self.calls.clear()
                result = self.invoke("--prometheus-port", str(self.server.server_port), mode=mode)
                self.assertEqual(1, result.returncode)
                self.assertIn("허용된 지표 조회 도구와 인자", result.stdout)
                self.assertEqual(2, len(self.calls))

    def test_metrics_rejects_wrong_handoff_and_marks_missing_samples(self):
        self.set_page(0, ledger([movement()]))
        self.set_metrics()
        result = self.invoke("--prometheus-port", str(self.server.server_port), mode="metrics_wrong_handoff")
        self.assertEqual(1, result.returncode)
        self.assertIn("전달 근거가 실제 조회 결과와 일치하지 않습니다", result.stdout)
        self.set_metrics(empty=True)
        result = self.invoke("--prometheus-port", str(self.server.server_port))
        self.assertEqual(1, result.returncode)
        self.assertIn("장애 판정 | 표본 부족", result.stdout)

    def test_metrics_can_follow_scoped_pending_with_ledger_error(self):
        self.set_page(0, {}, status=503)
        self.set_metrics()
        result = self.invoke("--prometheus-port", str(self.server.server_port))
        self.assertEqual(1, result.returncode)
        self.assertIn("폐기 에이전트의 E1 인계 확인", result.stdout)
        self.assertIn("보낸 차감 요청의 로그", result.stdout)
        self.assertNotIn("/retry", result.stdout)

    def test_metrics_skipped_for_unowned_or_terminal_disposal(self):
        for status, payload in ((404, {}), (200, disposal(status="COMPLETED"))):
            with self.subTest(status=status):
                self.calls.clear()
                self.routes[DETAIL] = status, payload
                self.invoke("--prometheus-port", str(self.server.server_port))
                self.assertEqual([("GET", DETAIL, f"Bearer {TOKEN}")], self.calls)
                self.assertFalse(self.agent_log.with_suffix(".metrics.json").exists())

    @unittest.skipUnless(os.environ.get("ERPMSA_TEST_LIVE_MODEL"), "실제 공급자 검증은 모델을 지정해 실행")
    def test_live_models_collaborate(self):
        self.set_page(0, ledger([movement()]))
        self.set_metrics()
        result = self.invoke("--prometheus-port", str(self.server.server_port),
                             "--model", os.environ["ERPMSA_TEST_LIVE_MODEL"], live=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(5, len(self.calls))
        self.assertIn("폐기 에이전트의 E1, E2 인계 확인", result.stdout)
        self.assertIn("차감 결과 응답부터 폐기 상태 확정", result.stdout)

    @unittest.skipUnless(os.environ.get("ERPMSA_TEST_LIVE_MODEL"), "실제 공급자 검증은 모델을 지정해 실행")
    def test_live_model_selects_read_only_tools(self):
        self.set_page(0, ledger([movement()]))
        scope = cli.Investigation(cli.LoopbackReader(self.server.server_port, TOKEN), DISPOSAL_ID, 10)
        cli.run_agent(scope, os.environ["ERPMSA_TEST_LIVE_MODEL"])
        self.assertEqual("matched", scope.conclusion)
        self.assertEqual(["E1", "E2"], [item["evidenceId"] for item in scope.evidence])
        self.assertEqual(2, len(self.calls))
        self.assertTrue(all(method == "GET" for method, _, _ in self.calls))

    @unittest.skipUnless(os.environ.get("ERPMSA_TEST_OPENCODE") == "1", "실제 OpenCode 2 검증은 명시적으로 실행")
    def test_actual_opencode_selects_scoped_mcp_tools(self):
        self.set_page(0, ledger([movement()]))
        provider_calls = []
        fixture = self

        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                provider_calls.append(body)
                step = len(provider_calls)
                if step <= 2:
                    name = "erp_get_disposal" if step == 1 else "erp_get_stock_movements"
                    arguments = "{}" if step == 1 else '{"page":0}'
                    delta = {"tool_calls": [{"index": 0, "id": f"call-{step}", "type": "function",
                                            "function": {"name": name, "arguments": arguments}}]}
                    finish = "tool_calls"
                else:
                    delta = {"content": '{"conclusion":"matched","evidence":["E1","E2"]}'}
                    finish = "stop"
                events = [
                    {"delta": delta, "finish_reason": None, "index": 0},
                    {"delta": {}, "finish_reason": finish, "index": 0},
                ]
                payload = "".join("data: " + json.dumps({
                    "id": "fixture", "object": "chat.completion.chunk", "created": 1,
                    "model": "fixture", "choices": [event],
                }) + "\n\n" for event in events) + "data: [DONE]\n\n"
                encoded = payload.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        with HTTPServer(("127.0.0.1", 0), Provider) as provider:
            thread = Thread(target=provider.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
            thread.start()
            original_popen = subprocess.Popen

            def use_fixture_provider(arguments, *args, **kwargs):
                if arguments[1] != "serve":
                    return original_popen(arguments, *args, **kwargs)
                env = kwargs["env"]
                config_file = Path(env["XDG_CONFIG_HOME"], "opencode/opencode.json")
                config = json.loads(config_file.read_text())
                config["providers"] = {"disposal-fixture": {
                    "name": "Disposal Fixture", "env": ["DISPOSAL_FIXTURE_KEY"],
                    "package": "@opencode/ai/providers/openai-compatible",
                    "settings": {"baseURL": f"http://127.0.0.1:{provider.server_port}/v1"},
                    "models": {"fixture": {"name": "Fixture"}},
                }}
                config_file.write_text(json.dumps(config))
                env["DISPOSAL_FIXTURE_KEY"] = "fixture-key"
                env["XDG_DATA_HOME"] = str(config_file.parent / "data")
                return original_popen(arguments, *args, **kwargs)

            investigation = cli.Investigation(cli.LoopbackReader(fixture.server.server_port, TOKEN), DISPOSAL_ID, 10)
            try:
                with patch.object(cli.subprocess, "Popen", side_effect=use_fixture_provider):
                    cli.run_agent(investigation, "disposal-fixture/fixture")
            finally:
                provider.shutdown()
                thread.join(2)
        self.assertEqual("matched", investigation.conclusion)
        self.assertEqual(3, len(provider_calls))
        for body in provider_calls[:2]:
            names = {tool["function"]["name"] for tool in body.get("tools", [])}
            self.assertEqual({"erp_get_disposal", "erp_get_stock_movements"}, names)
        transmitted = json.dumps(provider_calls, ensure_ascii=False)
        for secret in (TOKEN, REASON, DISPOSAL_ID, "user-input-request-id"):
            self.assertNotIn(secret, transmitted)
        self.assertEqual(2, len(self.calls))
        self.assertTrue(all(method == "GET" for method, _, _ in self.calls))


FAKE_AGENT = r'''
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

config = json.loads((Path(os.environ["XDG_CONFIG_HOME"]) / "opencode/opencode.json").read_text())
if sys.argv[1] == "serve":
    class Ready(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            payload = json.dumps({"data": [{"name": "erp", "status": {"status": "connected"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
    HTTPServer(("127.0.0.1", int(sys.argv[sys.argv.index("--port") + 1])), Ready).serve_forever()
    sys.exit(0)
server = config["mcp"]["servers"]["erp"]
url = urlsplit(server["url"])
mode = os.environ["FAKE_AI_MODE"]
record = {"config": config, "args": sys.argv[1:], "cwd": os.getcwd(),
          "token_in_env": "ERPMSA_ACCESS_TOKEN" in os.environ, "a2a_token_in_env": "ERPMSA_A2A_TOKEN" in os.environ,
          "tools": [], "tool_results": []}

def rpc(method, params=None):
    connection = http.client.HTTPConnection(url.hostname, url.port, timeout=3)
    headers = dict(server["headers"])
    headers["Authorization"] = headers["Authorization"].replace(
        "{env:ERPMSA_MCP_TOKEN}", os.environ["ERPMSA_MCP_TOKEN"]
    )
    headers["Content-Type"] = "application/json"
    if mode == "wrong_capability":
        headers["Authorization"] = "Bearer invalid"
    message = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        message["params"] = params
    connection.request("POST", url.path, body=json.dumps(message).encode(), headers=headers)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    if response.status != 200:
        return {}
    return json.loads(raw)

def call(name, arguments):
    record["tools"].append(name)
    response = rpc("tools/call", {"name": name, "arguments": arguments})
    result = json.loads(response["result"]["content"][0]["text"])
    record["tool_results"].append(result)
    return result

agent = sys.argv[sys.argv.index("--agent") + 1]
if agent == "erp-prometheus-investigator":
    handoff = json.loads(sys.argv[-1])
    catalog = rpc("tools/list")["result"]["tools"]
    if mode == "metrics_scope_escape":
        current = call("get_disposal", {})
    elif mode == "metrics_custom_query":
        current = call("get_service_metric", {"metric": "scrape", "query": "up"})
    else:
        for metric in ("p95_seconds", "http_5xx", "scrape"):
            current = call("get_service_metric", {"metric": metric})
            if "error" in current:
                break
    assessment = current.get("assessment", "insufficient")
    matched = handoff["disposalConclusion"] == "matched"
    next_check = {
        "signals_observed": "trace_disposal_result" if matched else "trace_stock_call",
        "insufficient": "verify_metric_coverage",
        "no_down_or_5xx": "review_disposal_state" if matched else "review_stock_history",
    }
    result = {
        "assessment": assessment, "disposalConclusion": handoff["disposalConclusion"],
        "disposalEvidence": ["E999"] if mode == "metrics_wrong_handoff" else handoff["disposalEvidence"],
        "evidence": [value["evidenceId"] for value in record["tool_results"] if "evidenceId" in value],
        "nextCheck": next_check[assessment],
    }
    Path(os.environ["FAKE_AI_LOG"]).with_suffix(".metrics.json").write_text(json.dumps({
        "handoff": handoff, "catalog": [tool["name"] for tool in catalog],
        "permissions": config["agents"][agent]["permissions"], "token_in_env": record["token_in_env"],
    }))
    print(json.dumps({"type": "text", "part": {"text": json.dumps(result)}}))
    sys.exit(0)

result = {"conclusion": "matched", "evidence": []}
if mode in ("auth_error", "quota_error"):
    error_type = "provider.auth" if mode == "auth_error" else "provider.quota"
    print(json.dumps({"type": "error", "error": {"type": error_type}}))
elif mode == "wrong_capability":
    rpc("tools/list")
elif mode == "unknown_method":
    assert rpc("retry_disposal")["error"]["code"] == -32601
elif mode != "no_tools":
    rpc("initialize", {"protocolVersion": "2025-03-26"})
    catalog = [tool["name"] for tool in rpc("tools/list")["result"]["tools"]]
    delegated = "delegate_prometheus" in catalog
    assert len(catalog) == (3 if delegated else 2)
    if mode == "a2a_early":
        assert "error" in call("delegate_prometheus", {})
    if mode == "write_tool":
        current = call("retry_disposal", {})
    elif mode == "override_id":
        current = call("get_disposal", {"disposalId": "another-id"})
    elif mode == "before_detail":
        current = call("get_stock_movements", {"page": 0})
    else:
        current = call("get_disposal", {})
        if mode == "override_material":
            current = call("get_stock_movements", {"page": 0, "foodMaterialId": 8})
        elif mode == "skip_page":
            current = call("get_stock_movements", {"page": 1})
        elif mode == "repeat":
            for _ in range(104):
                current = call("get_disposal", {})
                if "error" in current:
                    break
        elif mode != "early_finish":
            page = 0
            while current.get("conclusion") == "inconclusive" and "error" not in current:
                current = call("get_stock_movements", {"page": page})
                if current.get("nextPage") is None:
                    break
                page = current["nextPage"]
    result = {"conclusion": current.get("conclusion", "inconclusive"),
              "evidence": [value["evidenceId"] for value in record["tool_results"] if "evidenceId" in value]}
    result["evidence"] = list(dict.fromkeys(result["evidence"]))
    if mode == "wrong_conclusion":
        result["conclusion"] = "no_match"
    if mode == "invented_evidence":
        result["evidence"] = ["E999"]
    if delegated:
        result["prometheus"] = None
        pending = any(value.get("status") == "PENDING" for value in record["tool_results"])
        if pending and mode != "a2a_skip":
            remote = call("delegate_prometheus", {})
            if "error" not in remote:
                result["prometheus"] = remote
                if mode == "a2a_wrong_result":
                    result["prometheus"] = {**remote, "nextCheck": "unknown"}
Path(os.environ["FAKE_AI_LOG"]).write_text(json.dumps(record))
print(json.dumps({"type": "text", "part": {"text": json.dumps(result)}}))
'''


if __name__ == "__main__":
    unittest.main()
