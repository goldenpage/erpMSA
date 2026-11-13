#!/usr/bin/env python3
"""Run the Prometheus investigator as a separate loopback A2A runtime."""

import argparse
from dataclasses import dataclass, field
from datetime import datetime
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import signal
from threading import Event, Lock, Thread
from uuid import uuid4

from disposal_a2a import CARD_PATH, CONTENT_TYPE, SKILL_ID, UUID, VERSION, access_token, interface
from disposal_mcp import InvestigationError
from disposal_metrics import MetricsInvestigation
from investigate_disposal import DEFAULT_MODEL, LoopbackReader, bounded_int, run_metrics_agent


@dataclass
class Task:
    message_id: str
    request: dict
    snapshot: dict
    reference: str | None = None
    done: Event = field(default_factory=Event)


class TaskConflict(Exception):
    pass


class RuntimeBusy(Exception):
    pass


def request_fields(payload):
    if not isinstance(payload, dict) or set(payload) - {"message", "configuration"}:
        raise ValueError()
    message = payload.get("message")
    message_fields = {"messageId", "role", "parts"}
    if (not isinstance(message, dict) or not message_fields <= set(message)
            or message["role"] != "ROLE_USER" or not isinstance(message["messageId"], str)
            or not UUID.fullmatch(message["messageId"]) or not isinstance(message["parts"], list)):
        raise ValueError()
    [part] = message["parts"]
    if not isinstance(part, dict) or set(part) - {"data", "mediaType"} or part.get("mediaType", "application/json") != "application/json":
        raise ValueError()
    data = part.get("data")
    if not isinstance(data, dict) or type(data.get("windowEnd")) not in (int, float):
        raise ValueError()
    common = {"status", "windowEnd", "disposalConclusion", "disposalEvidence"}
    context_id = reference = None
    if data.get("status") == "COMPLETED":
        if (set(data) != common | {"completedAt", "stockComparison"} or data["disposalConclusion"] != "matched"
                or set(message) != message_fields | {"contextId", "referenceTaskIds"}):
            raise ValueError()
        comparison = data["stockComparison"]
        references = message["referenceTaskIds"]
        if (not isinstance(comparison, dict) or set(comparison) != {"inventory", "ledger"}
                or any(type(value) is not bool for value in comparison.values())
                or not isinstance(references, list) or len(references) != 1):
            raise ValueError()
        context_id, reference = message["contextId"], references[0]
        if not all(isinstance(value, str) and UUID.fullmatch(value) for value in (context_id, reference)):
            raise ValueError()
    elif (data.get("status") != "PENDING" or set(data) != common | {"createdAt"}
          or set(message) != message_fields or data["disposalConclusion"] not in ("matched", "no_match", "inconclusive")):
        raise ValueError()
    evidence = data["disposalEvidence"]
    minimum = 1 if data["disposalConclusion"] == "inconclusive" else 2
    if (not isinstance(evidence, list) or not minimum <= len(evidence) <= 101
            or evidence != [f"E{i}" for i in range(1, len(evidence) + 1)]):
        raise ValueError()
    config = payload.get("configuration", {})
    if not isinstance(config, dict) or set(config) - {"returnImmediately", "acceptedOutputModes", "historyLength"}:
        raise ValueError()
    immediate = config.get("returnImmediately", False)
    modes = config.get("acceptedOutputModes", ["application/json"])
    history_length = config.get("historyLength", 0)
    if (type(immediate) is not bool or not isinstance(modes, list) or "application/json" not in modes
            or type(history_length) is not int or history_length < 0):
        raise ValueError()
    return message["messageId"], data, immediate, context_id, reference


class MetricsServer(ThreadingHTTPServer):
    def __init__(self, port, token, get, model):
        super().__init__(("127.0.0.1", port), Handler)
        self.authorization = f"Bearer {token}".encode()
        self.get = get
        self.model = model
        self.tasks = {}
        self.lock = Lock()

    def card(self):
        description = "폐기 조사 근거를 받아 지정한 시각의 Prometheus 지표를 조회합니다."
        return {
            "name": "ERP Prometheus investigator", "description": description, "version": "1.0.0",
            "supportedInterfaces": [interface(self.server_port)],
            "capabilities": {"streaming": False, "pushNotifications": False},
            "securitySchemes": {"localBearer": {"httpAuthSecurityScheme": {"scheme": "Bearer"}}},
            "securityRequirements": [{"schemes": {"localBearer": {"list": []}}}],
            "defaultInputModes": ["application/json"], "defaultOutputModes": ["application/json"],
            "skills": [{"id": SKILL_ID, "name": "Prometheus incident investigation", "description": description,
                        "tags": ["erp", "prometheus", "read-only"]}],
        }

    def submit(self, message_id, data, context_id, reference):
        decision = {"conclusion": data["disposalConclusion"], "evidence": data["disposalEvidence"]}
        with self.lock:
            for task in self.tasks.values():
                if task.message_id == message_id:
                    if task.request != data or task.reference != reference or (
                        context_id and task.snapshot["contextId"] != context_id
                    ):
                        raise TaskConflict()
                    return task
            retry = None
            anchor = data.get("createdAt")
            if reference:
                prior = self.tasks.get(reference)
                if (prior is None or not prior.done.is_set() or prior.snapshot["contextId"] != context_id
                        or prior.snapshot["status"]["state"] != "TASK_STATE_COMPLETED"
                        or prior.request["status"] != "PENDING"
                        or prior.request["disposalConclusion"] not in ("matched", "no_match")):
                    raise ValueError()
                anchor = data["completedAt"]
                if (not isinstance(anchor, str) or "T" not in anchor
                        or data["windowEnd"] <= prior.request["windowEnd"]
                        or datetime.fromisoformat(anchor).timestamp() <= datetime.fromisoformat(prior.request["createdAt"]).timestamp()):
                    raise ValueError()
                artifact = prior.snapshot["artifacts"][0]["parts"][0]["data"]
                retry = {"stockComparison": data["stockComparison"], "previousAssessment": artifact["decision"]["assessment"],
                         "previousDisposalConclusion": prior.request["disposalConclusion"]}
            scope = MetricsInvestigation(self.get, anchor, decision, window_end=data["windowEnd"], retry=retry)
            if any(not task.done.is_set() for task in self.tasks.values()):
                raise RuntimeBusy()
            if len(self.tasks) >= 32:
                self.tasks.pop(next(iter(self.tasks)))
            task_id = str(uuid4())
            task = Task(message_id, data, {"id": task_id, "contextId": context_id or str(uuid4()),
                                          "status": {"state": "TASK_STATE_WORKING"}}, reference)
            worker = Thread(target=self.finish, args=(task, scope))
            worker.start()
            self.tasks[task_id] = task
            return task

    def finish(self, task, scope):
        try:
            decision = run_metrics_agent(scope, self.model)
            task.snapshot = {**task.snapshot, "status": {"state": "TASK_STATE_COMPLETED"}, "artifacts": [{
                "artifactId": str(uuid4()), "name": SKILL_ID, "parts": [{"mediaType": "application/json", "data": {
                    "windowEnd": scope.end, "metrics": list(scope.evidence.values()), "decision": decision,
                }}],
            }]}
        except Exception:
            task.snapshot = {**task.snapshot, "status": {"state": "TASK_STATE_FAILED", "message": {
                "role": "ROLE_AGENT", "messageId": str(uuid4()), "parts": [{"text": "Prometheus 조사를 완료하지 못했습니다."}],
            }}}
        finally:
            task.done.set()


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(3)

    def log_message(self, *args):
        pass

    def reply(self, status, payload, media_type=CONTENT_TYPE):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        if status == 401:
            self.send_header("WWW-Authenticate", "Bearer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def problem(self, status, code, message, reason=None):
        error = {"code": status, "status": code, "message": message}
        if reason:
            error["details"] = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                                 "reason": reason, "domain": "a2a-protocol.org"}]
        self.reply(status, {"error": error})

    def authorized(self):
        if self.headers.get("Origin") or not hmac.compare_digest(self.headers.get("Authorization", "").encode(), self.server.authorization):
            self.problem(401, "UNAUTHENTICATED", "A2A 인증이 필요합니다.")
            return False
        if self.headers.get("A2A-Version") != VERSION:
            self.problem(400, "FAILED_PRECONDITION", "A2A 1.0 인터페이스입니다.", "VERSION_NOT_SUPPORTED")
            return False
        return True

    def do_GET(self):
        if self.path == CARD_PATH:
            self.reply(200, self.server.card(), "application/json")
            return
        if not self.authorized():
            return
        task_id = self.path.removeprefix("/tasks/")
        if self.path.startswith("/tasks/") and UUID.fullmatch(task_id):
            with self.server.lock:
                task = self.server.tasks.get(task_id)
            if task:
                self.reply(200, task.snapshot)
                return
        self.problem(404, "NOT_FOUND", "A2A 태스크를 찾을 수 없습니다.", "TASK_NOT_FOUND")

    def do_POST(self):
        if not self.authorized():
            return
        if self.path != "/message:send":
            self.problem(400, "FAILED_PRECONDITION", "지원하는 위임 경로는 /message:send입니다.", "UNSUPPORTED_OPERATION")
            return
        if self.headers.get_content_type() not in (CONTENT_TYPE, "application/json"):
            self.problem(400, "INVALID_ARGUMENT", "JSON 요청 본문이 필요합니다.", "CONTENT_TYPE_NOT_SUPPORTED")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16384:
                raise ValueError()
            message_id, data, immediate, context_id, reference = request_fields(json.loads(self.rfile.read(length)))
            task = self.server.submit(message_id, data, context_id, reference)
        except (ValueError, OverflowError, RecursionError, OSError, InvestigationError):
            self.problem(400, "INVALID_ARGUMENT", "폐기 근거와 조회 구간이 A2A 요청 계약과 일치하지 않습니다.")
            return
        except TaskConflict:
            self.problem(409, "ALREADY_EXISTS", "같은 메시지 ID의 위임 내용이 다릅니다.")
            return
        except RuntimeBusy:
            self.problem(429, "RESOURCE_EXHAUSTED", "이미 진행 중인 조사가 있습니다.")
            return
        if not immediate:
            task.done.wait()
        self.reply(200, {"task": task.snapshot})


def stop_runtime(*_):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description="Prometheus 조회 전용 A2A 런타임")
    parser.add_argument("--port", type=bounded_int(1, 65535), default=8765)
    parser.add_argument("--prometheus-port", type=bounded_int(1, 65535), default=9090)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()
    if not re.fullmatch(r"[\w.-]+/[\w./:#-]+", args.model):
        parser.error("--model은 OpenCode의 provider/model 형식이어야 합니다.")
    try:
        token = access_token()
        signal.signal(signal.SIGTERM, stop_runtime)
        with MetricsServer(args.port, token, LoopbackReader(args.prometheus_port).get, args.model) as server:
            print(f"Prometheus A2A 1.0 | http://127.0.0.1:{server.server_port}{CARD_PATH}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (InvestigationError, OSError) as error:
        parser.exit(1, f"A2A 런타임 실행 실패 | {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
