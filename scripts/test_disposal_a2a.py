from datetime import datetime
import http.client
import json
from threading import Event, Thread
import unittest
from unittest.mock import patch
from uuid import uuid4

import investigate_disposal as cli
import serve_disposal_metrics as runtime
import test_investigate_disposal as fixtures
from disposal_a2a import CARD_PATH, CONTENT_TYPE, MetricsA2AClient, SKILL_ID, TOKEN_ENV, VERSION
from disposal_mcp import InvestigationError
from disposal_metrics import QUERIES


A2A_TOKEN = "fixture-token-for-local-a2a-runtime-123"


def request_payload():
    created = fixtures.CREATED_AT
    return {"message": {"messageId": str(uuid4()), "role": "ROLE_USER", "parts": [{
        "data": {"status": "PENDING", "createdAt": created,
                 "windowEnd": datetime.fromisoformat(created).timestamp() + 120,
                 "disposalConclusion": "matched", "disposalEvidence": ["E1", "E2"]},
        "mediaType": "application/json",
    }]}, "configuration": {"returnImmediately": True}}


def fixture_agent(scope, _):
    for metric in QUERIES:
        result = scope.call("get_service_metric", {"metric": metric})
        if "error" in result:
            raise InvestigationError(result["error"])
    next_check = "trace_disposal_result" if scope.handoff["disposalConclusion"] == "matched" else "trace_stock_call"
    if scope.handoff["status"] == "COMPLETED":
        return scope.validate_final(json.dumps(result["decision"]))
    decision = {"assessment": result["assessment"], "evidence": ["P1", "P2", "P3"],
                "disposalConclusion": scope.handoff["disposalConclusion"],
                "disposalEvidence": scope.handoff["disposalEvidence"], "nextCheck": next_check}
    return scope.validate_final(json.dumps(decision))


class DisposalA2ATest(unittest.TestCase):
    def setUp(self):
        self.erp = fixtures.DisposalCliTest()
        self.erp.setUp()
        self.addCleanup(self.erp.doCleanups)
        self.erp.set_page(0, fixtures.ledger([fixtures.movement()]))
        self.erp.set_metrics()
        self.server = runtime.MetricsServer(0, A2A_TOKEN, cli.LoopbackReader(self.erp.server.server_port).get, "fixture")
        thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, data=None, token=A2A_TOKEN, version=VERSION):
        headers = {"Authorization": f"Bearer {token}", "A2A-Version": version, "Content-Type": CONTENT_TYPE}
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, json.dumps(data) if data is not None else None, headers)
            with connection.getresponse() as response:
                return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_model_delegation_uses_validated_artifact_and_keeps_both_tokens_out(self):
        with patch.object(runtime, "run_metrics_agent", side_effect=fixture_agent) as agent, patch.dict("os.environ", {TOKEN_ENV: A2A_TOKEN}):
            result = self.erp.invoke("--a2a-port", str(self.server.server_port), mode="a2a_early")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("A2A 위임 완료", result.stdout)
        self.assertIn("차감 결과 응답부터 폐기 상태 확정", result.stdout)
        self.assertEqual(1, agent.call_count)
        self.assertEqual(5, len(self.erp.calls))
        task, = self.server.tasks.values()
        for secret in (fixtures.TOKEN, A2A_TOKEN, fixtures.DISPOSAL_ID, fixtures.REASON):
            self.assertNotIn(secret, json.dumps(task.request, ensure_ascii=False))
        record = json.loads(self.erp.agent_log.read_text())
        self.assertFalse(record["token_in_env"])
        self.assertFalse(record["a2a_token_in_env"])
        self.assertEqual("delegate_prometheus", record["tools"][-1])
        self.assertEqual(task.snapshot["id"], record["tool_results"][-1]["taskId"])

    def test_failed_peer_preserves_disposal_result(self):
        with patch.object(runtime, "run_metrics_agent", side_effect=InvestigationError("fixture")), patch.dict("os.environ", {TOKEN_ENV: A2A_TOKEN}):
            result = self.erp.invoke("--a2a-port", str(self.server.server_port))
        self.assertEqual(1, result.returncode)
        self.assertIn("재고 차감 원장 확인", result.stdout)
        self.assertIn("A2A 태스크가 완료 상태에 도달하지 못했습니다", result.stdout)
        self.assertEqual(2, len(self.erp.calls))

    def test_agent_must_delegate_and_cite_returned_result(self):
        with patch.object(runtime, "run_metrics_agent", side_effect=fixture_agent) as agent, patch.dict("os.environ", {TOKEN_ENV: A2A_TOKEN}):
            result = self.erp.invoke("--a2a-port", str(self.server.server_port), mode="a2a_skip")
            self.assertEqual(1, result.returncode)
            self.assertIn("A2A 위임을 수행하지 않았습니다", result.stdout)
            self.assertEqual(0, agent.call_count)
            result = self.erp.invoke("--a2a-port", str(self.server.server_port), mode="a2a_wrong_result")
        self.assertEqual(1, result.returncode)
        self.assertIn("최종 결론 또는 근거가 실제 조회 결과와 일치하지 않습니다", result.stdout)
        self.assertEqual(1, agent.call_count)

    def test_runtime_checks_auth_version_scope_and_idempotency(self):
        code, card = self.request("GET", CARD_PATH, token="")
        self.assertEqual(200, code)
        self.assertEqual(SKILL_ID, card["skills"][0]["id"])
        payload = request_payload()
        self.assertEqual(401, self.request("POST", "/message:send", payload, token="wrong")[0])
        self.assertEqual(400, self.request("POST", "/message:send", payload, version="0.3")[0])
        invalid = request_payload()
        invalid["message"]["parts"][0]["data"]["query"] = "up"
        self.assertEqual(400, self.request("POST", "/message:send", invalid)[0])
        self.assertEqual([], self.erp.calls)

        release = Event()

        def slow_agent(*args):
            if not release.wait(5):
                raise InvestigationError("fixture timed out")
            return fixture_agent(*args)

        with patch.object(runtime, "run_metrics_agent", side_effect=slow_agent) as agent:
            code, data = self.request("POST", "/message:send", payload)
            task_id = data["task"]["id"]
            task = self.server.tasks[task_id]
            try:
                self.assertEqual(200, code)
                self.assertEqual("TASK_STATE_WORKING", data["task"]["status"]["state"])
                self.assertEqual(task_id, self.request("POST", "/message:send", payload)[1]["task"]["id"])
                self.assertEqual(429, self.request("POST", "/message:send", request_payload())[0])
                payload["message"]["parts"][0]["data"]["disposalConclusion"] = "no_match"
                self.assertEqual(409, self.request("POST", "/message:send", payload)[0])
                self.assertEqual(401, self.request("GET", f"/tasks/{task_id}", token="wrong")[0])
            finally:
                release.set()
                self.assertTrue(task.done.wait(5))
        completed = self.request("GET", f"/tasks/{task_id}")[1]
        self.assertEqual("TASK_STATE_COMPLETED", completed["status"]["state"])
        self.assertEqual(SKILL_ID, completed["artifacts"][0]["name"])
        self.assertEqual(1, agent.call_count)

    def test_client_rejects_result_for_wrong_handoff(self):
        def tampered(scope, model):
            return {**fixture_agent(scope, model), "disposalEvidence": ["E999"]}

        client = MetricsA2AClient(self.server.server_port, A2A_TOKEN)
        with patch.object(runtime, "run_metrics_agent", side_effect=tampered):
            with self.assertRaises(InvestigationError):
                client.investigate(fixtures.CREATED_AT, {"conclusion": "matched", "evidence": ["E1", "E2"]})

    def test_follow_retry_keeps_context_and_compares_both_snapshots(self):
        completion = "2026-01-01T00:05:00Z"
        self.erp.set_metrics(anchor=completion)
        inventory = "/foodmaterials/inventories/7"
        self.erp.routes[inventory] = 200, {"foodMaterialId": 7, "inventoryId": 11, "onHandQuantity": 17, "version": 2}

        def lead(review, *_args, **_kwargs):
            detail = review.call("get_disposal", {})
            stock = review.call("get_stock_snapshot", {})
            summary = review.call("delegate_prometheus", {})
            self.assertNotIn("error", detail)
            self.assertNotIn("error", stock)
            self.assertNotIn("error", summary)
            if detail["status"] == "PENDING":
                self.erp.routes[fixtures.DETAIL] = 200, fixtures.disposal(
                    status="COMPLETED", movementId=9, quantityAfter=17, updatedAt=completion)
            return json.dumps({"conclusion": "matched", "evidence": ["E1", "E2"], "prometheus": summary})

        client = MetricsA2AClient(self.server.server_port, A2A_TOKEN)
        reader = cli.LoopbackReader(self.erp.server.server_port, fixtures.TOKEN)
        with patch.object(runtime, "run_metrics_agent", side_effect=fixture_agent), patch.object(
            cli, "run_scoped_agent", side_effect=lead
        ), patch("sys.stdout"):
            self.assertEqual(0, cli.run_retry_follow(reader, fixtures.DISPOSAL_ID, 10, client, "fixture", 1))
        prior, follow = self.server.tasks.values()
        self.assertEqual(prior.snapshot["id"], follow.reference)
        self.assertEqual(prior.snapshot["contextId"], follow.snapshot["contextId"])
        self.assertEqual("TASK_STATE_COMPLETED", follow.snapshot["status"]["state"])
        self.assertEqual({"inventory": True, "ledger": True}, follow.request["stockComparison"])
        self.assertEqual(17, len(self.erp.calls))
        self.assertTrue(all(method == "GET" for method, _, _ in self.erp.calls))

        payload = request_payload()
        message = payload["message"]
        message.update(contextId=str(uuid4()), referenceTaskIds=[prior.snapshot["id"]])
        message["parts"][0]["data"] = follow.request
        self.assertEqual(400, self.request("POST", "/message:send", payload)[0])

    def test_follow_retry_compares_changed_current_stock_without_a_success_claim(self):
        completed = "2026-01-01T00:05:00Z"
        self.erp.set_metrics(anchor=completed)
        path = "/foodmaterials/inventories/7"
        inventory = {"foodMaterialId": 7, "inventoryId": 11, "onHandQuantity": 17, "version": 2}
        self.erp.routes[path] = 200, inventory
        client = MetricsA2AClient(self.server.server_port, A2A_TOKEN)
        reader = cli.LoopbackReader(self.erp.server.server_port, fixtures.TOKEN)
        before = cli.RetryReview(reader, fixtures.DISPOSAL_ID, 10, client)
        with patch.object(runtime, "run_metrics_agent", side_effect=fixture_agent):
            before.call("get_disposal", {})
            before.call("get_stock_snapshot", {})
            before.call("delegate_prometheus", {})
            self.erp.routes[path] = 200, {**inventory, "onHandQuantity": 16, "version": 3}
            self.erp.routes[fixtures.DETAIL] = 200, fixtures.disposal(
                status="COMPLETED", movementId=9, quantityAfter=17, updatedAt=completed)
            after = cli.RetryReview(reader, fixtures.DISPOSAL_ID, 10, client, before)
            self.assertEqual("COMPLETED", after.call("get_disposal", {})["status"])
            self.assertEqual({"inventory": False, "ledger": True}, after.call("get_stock_snapshot", {})["stockComparison"])
            self.assertEqual("review_retry_evidence", after.call("delegate_prometheus", {})["nextCheck"])

    def test_follow_retry_accepts_only_one_expected_deduction_after_no_match(self):
        completed = "2026-01-01T00:05:00Z"
        self.erp.set_metrics(anchor=completed)
        path = "/foodmaterials/inventories/7"
        inventory = {"foodMaterialId": 7, "inventoryId": 11, "onHandQuantity": 20, "version": 1}
        self.erp.routes[path] = 200, inventory
        initial = fixtures.movement(movementId=8, requestId="initial", movementType="INITIAL")
        self.erp.set_page(0, fixtures.ledger([initial]))
        client = MetricsA2AClient(self.server.server_port, A2A_TOKEN)
        reader = cli.LoopbackReader(self.erp.server.server_port, fixtures.TOKEN)
        before = cli.RetryReview(reader, fixtures.DISPOSAL_ID, 10, client)
        with patch.object(runtime, "run_metrics_agent", side_effect=fixture_agent):
            self.assertEqual("PENDING", before.call("get_disposal", {})["status"])
            self.assertEqual("no_match", before.call("get_stock_snapshot", {})["conclusion"])
            self.assertEqual("trace_stock_call", before.call("delegate_prometheus", {})["nextCheck"])
            self.erp.routes[fixtures.DETAIL] = 200, fixtures.disposal(
                status="COMPLETED", movementId=9, quantityAfter=17, updatedAt=completed)
            for name, version, rows, expected in (
                ("one deduction", 2, [fixtures.movement(), initial], {"inventory": True, "ledger": True}),
                ("unexpected version", 3, [fixtures.movement(), initial], {"inventory": False, "ledger": True}),
                ("extra ledger row", 2, [fixtures.movement(), fixtures.movement(movementId=10, requestId="other"), initial],
                 {"inventory": True, "ledger": False}),
            ):
                with self.subTest(name=name):
                    self.erp.routes[path] = 200, {**inventory, "onHandQuantity": 17, "version": version}
                    self.erp.set_page(0, fixtures.ledger(rows))
                    after = cli.RetryReview(reader, fixtures.DISPOSAL_ID, 10, client, before)
                    self.assertEqual("COMPLETED", after.call("get_disposal", {})["status"])
                    self.assertEqual(expected, after.call("get_stock_snapshot", {})["stockComparison"])
                    summary = after.call("delegate_prometheus", {})
                    self.assertEqual("no_match", summary["previousDisposalConclusion"])
                    self.assertEqual("review_retry_signals" if all(expected.values()) else "review_retry_evidence",
                                     summary["nextCheck"])
                    self.assertEqual(expected, summary["stockComparison"])
        prior, *followups = self.server.tasks.values()
        self.assertTrue(all(task.reference == prior.snapshot["id"] for task in followups))
        self.assertTrue(all(task.snapshot["contextId"] == prior.snapshot["contextId"] for task in followups))
        self.assertTrue(all(method == "GET" for method, _, _ in self.erp.calls))


if __name__ == "__main__":
    unittest.main()
