"""Loopback A2A 1.0 HTTP+JSON client for Prometheus investigations."""

import http.client
import json
import math
import os
import re
import time
from uuid import uuid4

from disposal_mcp import InvestigationError
from disposal_metrics import JOBS, QUERIES, MetricsInvestigation


VERSION = "1.0"
CONTENT_TYPE = "application/a2a+json"
CARD_PATH = "/.well-known/agent-card.json"
SKILL_ID = "erp-prometheus-incident"
TOKEN_ENV = "ERPMSA_A2A_TOKEN"
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
DELEGATE_TOOL = {
    "name": "delegate_prometheus",
    "description": "확인한 폐기·원장 근거로 Prometheus 읽기 전용 조사를 A2A에 위임하고 결과를 받는다.",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    "annotations": {"readOnlyHint": True, "destructiveHint": False},
}


def access_token():
    token = os.environ.get(TOKEN_ENV, "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
        raise InvestigationError(f"{TOKEN_ENV}에 32자 이상의 URL-safe 공유 토큰을 설정하세요.")
    return token


def interface(port):
    return {"url": f"http://127.0.0.1:{port}", "protocolBinding": "HTTP+JSON", "protocolVersion": VERSION}


class MetricsA2AClient:
    def __init__(self, port, token):
        self.port = port
        self.token = token

    def request(self, method, path, payload=None):
        headers = {"A2A-Version": VERSION, "Accept": CONTENT_TYPE}
        if path != CARD_PATH:
            headers["Authorization"] = f"Bearer {self.token}"
        body = None
        if payload is not None:
            headers["Content-Type"] = CONTENT_TYPE
            body = json.dumps(payload).encode()
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request(method, path, body, headers)
            with connection.getresponse() as response:
                if response.status != 200:
                    raise InvestigationError(f"Prometheus A2A 요청 실패 (HTTP {response.status}).")
                raw = response.read(65537)
        except (OSError, http.client.HTTPException) as error:
            raise InvestigationError("Prometheus A2A 런타임 연결 실패 또는 시간 초과.") from error
        finally:
            connection.close()
        try:
            data = json.loads(raw) if len(raw) <= 65536 else None
        except (ValueError, RecursionError) as error:
            raise InvestigationError("Prometheus A2A 응답을 해석할 수 없습니다.") from error
        if not isinstance(data, dict):
            raise InvestigationError("Prometheus A2A 응답 형식이 예상과 다릅니다.")
        return data

    def investigate(self, created_at, disposal, *, previous=None, comparison=None):
        retry = None
        if previous is not None:
            prior_id, prior_metrics, prior_decision = previous
            retry = {"stockComparison": comparison, "previousAssessment": prior_decision["assessment"],
                     "previousDisposalConclusion": prior_decision["disposalConclusion"]}
        metrics = MetricsInvestigation(None, created_at, disposal, retry=retry)
        card = self.request("GET", CARD_PATH)
        interfaces = card.get("supportedInterfaces")
        skills = card.get("skills")
        if (not isinstance(interfaces, list) or interface(self.port) not in interfaces
                or not isinstance(skills, list)
                or not any(isinstance(skill, dict) and skill.get("id") == SKILL_ID for skill in skills)):
            raise InvestigationError("Prometheus Agent Card에 지정한 A2A 인터페이스와 스킬이 없습니다.")
        data = {"createdAt": created_at, "windowEnd": metrics.end, **metrics.handoff}
        message = {"role": "ROLE_USER", "messageId": str(uuid4()),
                   "parts": [{"data": data, "mediaType": "application/json"}]}
        if previous is not None:
            data["completedAt"] = data.pop("createdAt")
            del data["previousAssessment"]
            del data["previousDisposalConclusion"]
            message.update(contextId=prior_metrics.a2a_context_id, referenceTaskIds=[prior_id])
        response = self.request("POST", "/message:send", {
            "message": message,
            "configuration": {"returnImmediately": True, "acceptedOutputModes": ["application/json"]},
        })
        task = response.get("task")
        task_id = task.get("id") if isinstance(task, dict) else None
        context_id = task.get("contextId") if isinstance(task, dict) else None
        if not all(isinstance(value, str) and UUID.fullmatch(value) for value in (task_id, context_id)):
            raise InvestigationError("Prometheus A2A 태스크 식별자를 확인하지 못했습니다.")
        if previous is not None and (context_id != prior_metrics.a2a_context_id or task_id == prior_id):
            raise InvestigationError("재시도 후 A2A 태스크가 이전 조사 맥락과 일치하지 않습니다.")
        metrics.a2a_context_id = context_id
        deadline = time.monotonic() + 145
        while True:
            status = task.get("status")
            state = status.get("state") if isinstance(status, dict) else None
            if state == "TASK_STATE_COMPLETED":
                return task_id, metrics, accept_artifact(metrics, task)
            if state not in ("TASK_STATE_SUBMITTED", "TASK_STATE_WORKING"):
                raise InvestigationError("Prometheus A2A 태스크가 완료 상태에 도달하지 못했습니다.")
            if time.monotonic() >= deadline:
                raise InvestigationError("Prometheus A2A 태스크 대기 시간이 초과됐습니다.")
            time.sleep(0.5)
            task = self.request("GET", f"/tasks/{task_id}")
            if task.get("id") != task_id or task.get("contextId") != context_id:
                raise InvestigationError("Prometheus A2A 태스크 응답이 위임한 태스크와 일치하지 않습니다.")


def accept_artifact(metrics, task):
    try:
        [artifact] = task["artifacts"]
        [part] = artifact["parts"]
        result = part["data"]
        if (artifact["name"] != SKILL_ID or part.get("mediaType") != "application/json"
                or set(result) != {"windowEnd", "metrics", "decision"} or result["windowEnd"] != metrics.end
                or not isinstance(result["metrics"], list) or len(result["metrics"]) != len(QUERIES)):
            raise ValueError()
        for index, row in enumerate(result["metrics"], start=1):
            metric, values = row["metric"], row["values"]
            if (set(row) != {"metric", "values", "evidenceId"} or row["evidenceId"] != f"P{index}"
                    or metric not in QUERIES or metric in metrics.evidence or set(values) != set(JOBS)):
                raise ValueError()
            for value in values.values():
                if value is not None and (type(value) not in (int, float) or not math.isfinite(value)
                                          or value < 0 or (metric == "scrape" and value not in (0, 1))):
                    raise ValueError()
            metrics.evidence[metric] = row
        return metrics.validate_final(json.dumps(result["decision"]))
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError) as error:
        raise InvestigationError("Prometheus A2A 아티팩트가 위임 범위 또는 지표 형식과 일치하지 않습니다.") from error
