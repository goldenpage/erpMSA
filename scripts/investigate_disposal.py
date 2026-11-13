#!/usr/bin/env python3
"""Investigate one pending disposal through the local ERP Gateway."""

import argparse
import base64
import getpass
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import warnings

from disposal_a2a import DELEGATE_TOOL, TOKEN_ENV as A2A_TOKEN_ENV, MetricsA2AClient, access_token as a2a_access_token
from disposal_mcp import DISPOSAL_TOOLS, InvestigationError, ReadOnlyMcp
from disposal_metrics import METRICS_AGENT, METRICS_INSTRUCTIONS, METRICS_TOOLS, RETRY_METRICS_INSTRUCTIONS, MetricsInvestigation


PAGE_SIZE = 100
MAX_BODY_BYTES = 1024 * 1024
TOKEN_ENV = "ERPMSA_ACCESS_TOKEN"
DISPOSAL_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
DEFAULT_MODEL = "opencode/deepseek-v4.1-flash-free"
AGENT = "erp-disposal-investigator"


def bounded_int(minimum, maximum):
    def parse(value):
        number = int(value)
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(f"{minimum}~{maximum} 사이의 정수가 필요합니다.")
        return number

    return parse


def access_token():
    token = os.environ.get(TOKEN_ENV)
    if not token and sys.stdin.isatty():
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            try:
                token = getpass.getpass("ERP Access Token (입력 숨김): ")
            except (EOFError, getpass.GetPassWarning):
                token = None
    if not token or not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){2}", token):
        raise InvestigationError(f"유효한 ERP Access Token을 입력하거나 {TOKEN_ENV} 환경변수로 제공하세요.")
    return token


class LoopbackReader:
    def __init__(self, port, token=None):
        self.port = port
        self.token = token

    def get(self, path, source):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            headers = {"Accept": "application/json"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            connection.request("GET", path, headers=headers)
            with connection.getresponse() as response:
                if response.status != 200:
                    hint = ""
                    if self.token:
                        hint = {
                            401: "Access Token의 만료 여부를 확인하세요.",
                            403: "조회 권한을 확인하세요.",
                            404: "현재 계정에서 조회 가능한 기록과 ID를 확인하세요.",
                        }.get(response.status, "로컬 Gateway와 대상 서비스 상태를 확인하세요.")
                    raise InvestigationError(f"{source} 조회 실패 (HTTP {response.status}). {hint}".rstrip())
                body = response.read(MAX_BODY_BYTES + 1)
                if len(body) > MAX_BODY_BYTES:
                    raise InvestigationError(f"{source} 응답이 크기 제한을 초과했습니다.")
        except (OSError, http.client.HTTPException) as error:
            raise InvestigationError(f"{source} 연결 실패 또는 시간 초과.") from error
        finally:
            connection.close()

        try:
            data = json.loads(body)
        except (ValueError, RecursionError) as error:
            raise InvestigationError(f"{source} 응답을 JSON으로 해석할 수 없습니다.") from error
        if not isinstance(data, dict):
            raise InvestigationError(f"{source} 응답 형식이 예상과 다릅니다.")
        return data


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def ledger_page(data, page):
    total = data.get("totalElements")
    pages = data.get("totalPages")
    movements = data.get("movements")
    if (
        not integer(data.get("page")) or data["page"] != page
        or data.get("size") != PAGE_SIZE or type(data.get("size")) is not int
        or not integer(total) or not integer(pages)
        or pages != (total + PAGE_SIZE - 1) // PAGE_SIZE
        or not isinstance(movements, list)
        or len(movements) != max(0, min(PAGE_SIZE, total - page * PAGE_SIZE))
    ):
        raise InvestigationError("원장 페이지 정보와 응답 건수가 일치하지 않습니다.")
    return total, pages, movements


def validated_movement(disposal, matches):
    movement = matches[0]
    delta = movement.get("quantityDelta")
    before = movement.get("quantityBefore")
    after = movement.get("quantityAfter")
    if (len(matches) != 1 or not integer(movement.get("foodMaterialId"), 1)
            or movement["foodMaterialId"] != disposal["foodMaterialId"]
            or movement.get("movementType") != "DISPOSAL"
            or type(delta) is not int or delta != -disposal["quantity"]
            or movement.get("reason") != disposal["reason"]
            or not integer(before) or not integer(after) or before + delta != after):
        raise InvestigationError("같은 키의 원장이 있지만 건수·유형·식자재·수량·사유 대조에 실패했습니다.")
    return movement


class Investigation:
    def __init__(self, gateway, disposal_id, max_pages, a2a=None):
        self.gateway = gateway
        self.disposal_id = disposal_id
        self.max_pages = max_pages
        self.disposal = None
        self.pages = {}
        self.seen_ids = set()
        self.total = None
        self.match = None
        self.conclusion = "inconclusive"
        self.failure = None
        self.evidence = []
        self.calls = 0
        self.a2a = a2a
        self.metrics_task = None
        self.metrics_error = None

    def call(self, name, arguments):
        self.calls += 1
        if name == "delegate_prometheus" and self.a2a is not None:
            return self.delegate_prometheus(arguments)
        try:
            if self.failure:
                raise InvestigationError(self.failure)
            if self.calls > self.max_pages + 3:
                raise InvestigationError("조회 도구 호출 한도에 도달했습니다.")
            if not isinstance(arguments, dict):
                raise InvestigationError("조회 도구 인자는 객체여야 합니다.")
            if name == "get_disposal" and not arguments:
                return self.detail()
            if name == "get_stock_movements" and set(arguments) == {"page"}:
                if not integer(arguments["page"]):
                    raise InvestigationError("원장 페이지는 0 이상의 정수여야 합니다.")
                return self.stock(arguments["page"])
            raise InvestigationError("허용된 조회 도구와 인자만 사용할 수 있습니다.")
        except InvestigationError as error:
            self.failure = str(error)
            self.conclusion = "inconclusive"
            return {"error": self.failure, "conclusion": "inconclusive"}

    def delegate_prometheus(self, arguments):
        if not isinstance(arguments, dict) or arguments or self.calls > self.max_pages + 3:
            return {"error": "A2A 위임은 허용된 호출 한도 안에서 인자 없이 요청하세요."}
        if (not self.disposal or self.disposal["status"] != "PENDING"
                or (self.conclusion == "inconclusive" and not self.failure)):
            return {"error": "PENDING 폐기의 원장 대조 결과 또는 조회 실패를 먼저 확인하세요."}
        if self.metrics_task is None and self.metrics_error is None:
            decision = {"conclusion": self.conclusion, "evidence": [item["evidenceId"] for item in self.evidence]}
            try:
                self.metrics_task = self.a2a.investigate(self.disposal.get("createdAt"), decision)
            except InvestigationError as error:
                self.metrics_error = str(error)
        if self.metrics_error:
            return {"error": self.metrics_error}
        return self.metrics_summary()

    def metrics_summary(self):
        if self.metrics_task is None:
            return None
        task_id, _, decision = self.metrics_task
        result = {"taskId": task_id, "assessment": decision["assessment"], "nextCheck": decision["nextCheck"],
                  "evidence": decision["evidence"]}
        if "stockComparison" in decision:
            result.update(stockComparison=decision["stockComparison"], previousAssessment=decision["previousAssessment"],
                          previousDisposalConclusion=decision["previousDisposalConclusion"])
        return result

    def record(self, facts):
        result = {"evidenceId": f"E{len(self.evidence) + 1}", **facts}
        self.evidence.append(result)
        return result

    def read_detail(self):
        disposal = self.gateway.get(f"/disposals/{self.disposal_id}", "폐기 상세")
        if (
            disposal.get("disposalId") != self.disposal_id
            or disposal.get("status") not in ("PENDING", "COMPLETED", "REJECTED")
            or not integer(disposal.get("foodMaterialId"), 1)
            or not integer(disposal.get("quantity"), 1)
            or not isinstance(disposal.get("reason"), str) or not disposal["reason"]
        ):
            raise InvestigationError("폐기 상세의 ID, 상태 또는 식자재·수량·사유가 예상과 다릅니다.")
        return disposal

    def detail(self):
        if self.disposal is not None:
            return self.evidence[0]
        disposal = self.read_detail()
        self.disposal = disposal
        status = disposal["status"]
        if status != "PENDING":
            self.conclusion = "not_pending"
        return self.record({"status": status, "conclusion": self.conclusion})

    def stock(self, page):
        if self.disposal is None or self.disposal["status"] != "PENDING":
            raise InvestigationError("PENDING 폐기 상세를 먼저 조회해야 합니다.")
        if page in self.pages:
            return self.pages[page]
        if self.conclusion != "inconclusive":
            raise InvestigationError("조사에 필요한 원장 조회가 이미 완료됐습니다.")
        if page != len(self.pages) or page >= self.max_pages:
            raise InvestigationError("원장은 한도 안에서 0페이지부터 순서대로 조회해야 합니다.")
        material = self.disposal["foodMaterialId"]
        path = f"/foodmaterials/inventories/{material}/movements?page={page}&size={PAGE_SIZE}"
        total, pages, movements = ledger_page(self.gateway.get(path, f"원장 {page + 1}페이지"), page)
        if self.total is not None and total != self.total:
            raise InvestigationError("조회 중 원장 건수가 바뀌었습니다.")
        matches = []
        for movement in movements:
            if not isinstance(movement, dict):
                raise InvestigationError("원장 항목 형식이 예상과 다릅니다.")
            identifier = movement.get("movementId")
            request_id = movement.get("requestId")
            if not integer(identifier, 1) or not isinstance(request_id, str) or not request_id:
                raise InvestigationError("원장 항목의 식별자가 비어 있거나 잘못됐습니다.")
            if identifier in self.seen_ids:
                raise InvestigationError("원장 조회 중 같은 항목이 중복으로 반환됐습니다.")
            self.seen_ids.add(identifier)
            if request_id == f"DISPOSAL-{self.disposal_id}":
                matches.append(movement)
            elif not integer(movement.get("foodMaterialId"), 1) or movement["foodMaterialId"] != material:
                raise InvestigationError("조회 대상과 다른 식자재의 원장 항목을 받았습니다.")
        if matches:
            self.match = validated_movement(self.disposal, matches)
            self.conclusion = "matched"
        elif page + 1 >= pages:
            self.conclusion = "no_match"
        elif page + 1 >= self.max_pages:
            self.failure = f"원장 {pages}페이지 중 {self.max_pages}페이지만 확인했습니다. --max-pages를 조정하세요."
        self.total = total
        result = self.record({
            "page": page, "totalPages": pages, "conclusion": self.conclusion,
            "nextPage": page + 1 if self.conclusion == "inconclusive" and not self.failure else None,
        })
        self.pages[page] = result
        return result

    def validate_final(self, text):
        if self.failure:
            raise InvestigationError(self.failure)
        try:
            decision = json.loads(text)
        except (ValueError, RecursionError) as error:
            raise InvestigationError("에이전트의 최종 결론을 해석할 수 없습니다.") from error
        evidence = [item["evidenceId"] for item in self.evidence]
        expected = {"conclusion": self.conclusion, "evidence": evidence}
        if self.a2a is not None:
            expected["prometheus"] = self.metrics_summary()
            if self.disposal and self.disposal["status"] == "PENDING" and not (self.metrics_task or self.metrics_error):
                raise InvestigationError("폐기 에이전트가 Prometheus A2A 위임을 수행하지 않았습니다.")
        if not evidence or decision != expected:
            raise InvestigationError("에이전트의 최종 결론 또는 근거가 실제 조회 결과와 일치하지 않습니다.")
        if self.conclusion == "inconclusive":
            raise InvestigationError("에이전트가 필요한 원장 조회를 완료하지 못했습니다.")
        return decision

    def report(self):
        if self.disposal:
            record = self.disposal
            print(f"폐기 상세 (GET /disposals/{self.disposal_id}) | {record['status']}, "
                  f"식자재 {record['foodMaterialId']}, 요청 수량 {record['quantity']}")
        for evidence in self.evidence:
            if "page" in evidence:
                print(f"근거 {evidence['evidenceId']} | 원장 {evidence['page'] + 1}페이지 조회")
            else:
                print(f"근거 {evidence['evidenceId']} | 폐기 상세 조회")
        if self.conclusion == "not_pending":
            action = "처리 완료 상태를 확인했습니다." if self.disposal["status"] == "COMPLETED" else "폐기 상세의 거절 사유를 확인하세요."
            print(f"판정 | 조사 대상 아님\n다음 조치 | {action}")
            return
        if self.match:
            row = self.match
            print(f"판정 | 재고 차감 원장 확인 (movementId={row['movementId']})")
            print(f"근거 | 유형 DISPOSAL, 수량 {row['quantityBefore']} → {row['quantityAfter']} "
                  f"({row['quantityDelta']:+d}), 식자재·수량·사유 일치")
        else:
            print(f"판정 | 조회한 원장 {self.total}건에서 해당 키를 찾지 못했습니다.")
            print("근거 | 폐기 상세와 원장은 별도 조회이므로 차감 여부는 미확정입니다.")
        print("다음 조치 | 현재 상태를 다시 확인하고 여전히 PENDING이면 운영자가 동일 ID의 "
              f"POST /disposals/{self.disposal_id}/retry를 사용하세요.")


class RetryReview(Investigation):
    """Capture a stable, bounded stock snapshot on each side of an operator retry."""

    def __init__(self, gateway, disposal_id, max_pages, a2a, baseline=None):
        super().__init__(gateway, disposal_id, max_pages, a2a)
        self.baseline = baseline
        self.expected_status = "COMPLETED" if baseline else "PENDING"
        self.inventory = self.rows = self.comparison = None

    def call(self, name, arguments):
        self.calls += 1
        try:
            if self.failure:
                raise InvestigationError(self.failure)
            if self.calls > 6 or arguments != {}:
                raise InvestigationError("정해진 조회 도구를 인자 없이 호출하세요.")
            if name == "get_disposal":
                if self.disposal is None:
                    self.disposal = self.read_detail()
                    if self.disposal["status"] != self.expected_status:
                        raise InvestigationError(f"{self.expected_status} 폐기 상태를 확인하지 못했습니다.")
                    if self.baseline and any(
                        self.disposal.get(key) != self.baseline.disposal.get(key)
                        for key in ("requestId", "foodMaterialId", "quantity", "reason", "createdAt")
                    ):
                        raise InvestigationError("재시도 후 폐기 상세가 이전 요청과 일치하지 않습니다.")
                    self.record({"status": self.expected_status})
                return self.evidence[0]
            if name == "get_stock_snapshot" and self.disposal is not None:
                if self.inventory is None:
                    self.capture_stock()
                return self.evidence[1]
            if name == "delegate_prometheus" and self.conclusion in ("matched", "no_match"):
                if self.metrics_task is None:
                    decision = {"conclusion": self.conclusion, "evidence": [item["evidenceId"] for item in self.evidence]}
                    if self.baseline:
                        self.metrics_task = self.a2a.investigate(
                            self.disposal.get("updatedAt"), decision,
                            previous=self.baseline.metrics_task, comparison=self.comparison,
                        )
                    else:
                        self.metrics_task = self.a2a.investigate(self.disposal.get("createdAt"), decision)
                return self.metrics_summary()
            raise InvestigationError("폐기 상세, 재고·원장, A2A 위임 순서로 조사하세요.")
        except InvestigationError as error:
            self.failure = str(error)
            return {"error": self.failure}

    def capture_stock(self):
        material = self.disposal["foodMaterialId"]
        path = f"/foodmaterials/inventories/{material}"
        inventory = self.gateway.get(path, "현재고")
        if (not integer(inventory.get("foodMaterialId"), 1) or inventory["foodMaterialId"] != material
                or not integer(inventory.get("inventoryId"), 1) or not integer(inventory.get("version"))
                or not integer(inventory.get("onHandQuantity"))):
            raise InvestigationError("현재고 응답이 조사 대상과 일치하지 않습니다.")
        rows = []
        for page in range(self.max_pages):
            data = self.gateway.get(f"{path}/movements?page={page}&size={PAGE_SIZE}", "재고 원장")
            total, pages, movements = ledger_page(data, page)
            if pages > self.max_pages or (page and total != self.total):
                raise InvestigationError("전체 재고 원장을 안정적으로 조회할 수 없습니다.")
            self.total = total
            rows.extend(movements)
            if page + 1 >= pages:
                break
        if any(not isinstance(row, dict) or not integer(row.get("movementId"), 1)
               or not integer(row.get("foodMaterialId"), 1) or row["foodMaterialId"] != material
               or not isinstance(row.get("requestId"), str) or not row["requestId"] for row in rows):
            raise InvestigationError("재고 원장 항목이 조사 대상과 일치하지 않습니다.")
        if len({row["movementId"] for row in rows}) != len(rows):
            raise InvestigationError("재고 원장에 중복 항목이 있습니다.")
        matches = [row for row in rows if row["requestId"] == f"DISPOSAL-{self.disposal_id}"]
        match = validated_movement(self.disposal, matches) if matches else None
        if self.baseline and (match is None or self.disposal.get("movementId") != match["movementId"]
                              or self.disposal.get("quantityAfter") != match["quantityAfter"]):
            raise InvestigationError("COMPLETED 폐기가 가리키는 원장이 실제 조회 결과와 다릅니다.")
        if self.gateway.get(path, "현재고 재확인") != inventory or self.read_detail() != self.disposal:
            raise InvestigationError("조회 중 현재고 또는 폐기 상태가 바뀌었습니다.")
        self.inventory, self.rows, self.match = inventory, rows, match
        self.conclusion = "matched" if match else "no_match"
        facts = {"conclusion": self.conclusion}
        if self.baseline:
            self.comparison = self.compare_stock()
            facts["stockComparison"] = self.comparison
        self.record(facts)

    def compare_stock(self):
        before = self.baseline
        if before.match:
            return {"inventory": self.inventory == before.inventory, "ledger": self.rows == before.rows}
        inventory, previous = self.inventory, before.inventory
        return {
            "inventory": (
                inventory["inventoryId"] == previous["inventoryId"]
                and inventory["version"] == previous["version"] + 1
                and self.match["quantityBefore"] == previous["onHandQuantity"]
                and self.match["quantityAfter"] == inventory["onHandQuantity"]
            ),
            "ledger": [row for row in self.rows if row["movementId"] != self.match["movementId"]] == before.rows,
        }

    def validate_final(self, text):
        if not self.metrics_task and not self.failure:
            raise InvestigationError("재시도 추적에는 각 단계의 A2A 완료 결과가 필요합니다.")
        return super().validate_final(text)


RETRY_TOOLS = [DISPOSAL_TOOLS[0], {
    "name": "get_stock_snapshot",
    "description": "현재고와 재고 원장을 읽고 같은 폐기 요청을 대조한다. 완료 단계에서는 재시도 전 결과와 비교한다.",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    "annotations": {"readOnlyHint": True, "destructiveHint": False},
}, DELEGATE_TOOL]

RETRY_INSTRUCTIONS = """
선택된 폐기 요청의 상태, 현재고·원장, Prometheus 지표를 읽어 재시도 추적 단계를 완료한다.
erp_get_disposal, erp_get_stock_snapshot, erp_delegate_prometheus를 순서대로 인자 없이 각각 한 번 호출한다.
완료 단계의 stockComparison은 이미 조회한 재시도 전후 ERP 근거의 비교 결과다.
오류가 있으면 추가 호출을 중단한다.
최종 답변은 설명 없이 {"conclusion":"matched 또는 no_match","evidence":["E1","E2"],"prometheus":{}} 형식의 JSON이다.
conclusion과 evidence는 도구의 실제 결과를 사용하고, prometheus에는 위임 도구가 반환한 객체를 그대로 넣는다.
"""


AGENT_INSTRUCTIONS = """
선택된 폐기 한 건의 재고 차감 여부를 조사한다.
erp_get_disposal과 erp_get_stock_movements만 사용한다.
먼저 폐기 상세를 조회한다. PENDING이면 0페이지부터 원장을 조회하고,
conclusion이 inconclusive이고 nextPage가 있으면 다음 페이지를 조회한다.
같은 도구를 다시 선택할 수 있지만 호출 한도를 지킨다. 도구 오류가 발생하면 조사를 중단한다.
완료 시 다른 글이나 마크다운 없이 JSON만 출력한다.
형식은 {"conclusion":"matched|no_match|not_pending|inconclusive","evidence":["E1","E2"]}다.
실제 도구가 반환한 conclusion과 모든 evidenceId를 발급 순서대로 사용한다.
matched는 재고 차감 원장 확인, no_match는 조회한 원장에서 미발견을 뜻한다.
폐기 상태 확정과 재고 차감 여부는 별개다.
"""
A2A_INSTRUCTIONS = """
이 실행에는 A2A 위임이 활성화됐다. 폐기·원장 도구에 더해 erp_delegate_prometheus를 사용할 수 있다.
상세가 PENDING이며 원장 대조가 matched, no_match, 조회 실패 또는 페이지 한도로 끝났다면 최종 답변 전에
erp_delegate_prometheus를 인자 없이 호출하고 결과를 기다린다. PENDING 상세를 확인하기 전의 오류는 위임하지 않는다.
최종 JSON에는 conclusion과 evidence 외에 prometheus를 추가한다.
위임이 성공하면 prometheus에 위임 도구가 반환한 taskId, assessment, nextCheck, evidence 객체를 그대로 넣는다.
위임 도구 오류 또는 PENDING 이외 상태라면 prometheus는 null이다. 위임 결과는 폐기 결론을 바꾸지 않는다.
"""


def execute_opencode(workdir, env, model, agent, prompt, timeout):
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    password = secrets.token_urlsafe(32)
    env["OPENCODE_SERVER_PASSWORD"] = password
    authorization = base64.b64encode(f"opencode:{password}".encode()).decode()
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(
            ["opencode", "serve", "--hostname", "127.0.0.1", "--port", str(port)],
            cwd=workdir, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
        )
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and process.poll() is None:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                try:
                    connection.request("GET", "/api/mcp", headers={"Authorization": f"Basic {authorization}"})
                    with connection.getresponse() as response:
                        status = json.loads(response.read(65536)) if response.status == 200 else {}
                    servers = status.get("data", [])
                    if any(item.get("name") == "erp" and item.get("status", {}).get("status") == "connected" for item in servers):
                        # OpenCode 2.0.18 debounces MCP tool registration by 100 ms after connection.
                        time.sleep(0.2)
                        break
                except (OSError, http.client.HTTPException, ValueError):
                    pass
                finally:
                    connection.close()
                time.sleep(0.05)
            else:
                raise InvestigationError("OpenCode의 조회 도구 연결을 확인하지 못했습니다.")
            return subprocess.run(
                ["opencode", "run", "--server", f"http://127.0.0.1:{port}", "--agent", agent, "--model", model,
                 "--format", "json", "--title", agent, "--", prompt],
                cwd=workdir, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                encoding="utf-8", timeout=timeout,
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def run_scoped_agent(investigation, model, *, agent, instructions, tools, steps, prompt, timeout=120):
    permissions = [{"action": "*", "resource": "*", "effect": "deny"}]
    for tool in tools:
        permissions.append({"action": f"erp_{tool['name']}", "resource": "*", "effect": "allow"})
    env = {key: value for key, value in os.environ.items()
           if key not in (TOKEN_ENV, A2A_TOKEN_ENV, "PWD") and (not key.startswith("OPENCODE_") or key == "OPENCODE_API_KEY")}
    env.update({
        "OPENCODE_PURE": "1", "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
        "OPENCODE_DISABLE_CLAUDE_CODE": "1", "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
    })
    with ReadOnlyMcp(investigation, tools) as endpoint, tempfile.TemporaryDirectory(prefix="erpmsa-opencode-") as workdir:
        workdir = str(Path(workdir).resolve())
        config = {
            "permissions": permissions, "snapshots": False, "update": "disable",
            "agents": {agent: {
                "description": "Investigate a scoped ERP incident using read tools",
                "mode": "primary", "permissions": permissions,
                "steps": steps, "system": instructions,
            }},
            "mcp": {"servers": {"erp": endpoint.config()}},
        }
        config_home = Path(workdir, "config")
        config_dir = config_home / "opencode"
        config_dir.mkdir(parents=True)
        (config_dir / "opencode.json").write_text(json.dumps(config), encoding="utf-8")
        env["XDG_CONFIG_HOME"] = str(config_home)
        try:
            result = execute_opencode(workdir, env, model, agent, prompt, timeout)
        except (OSError, subprocess.SubprocessError) as error:
            raise InvestigationError("OpenCode 실행 실패 또는 조사 시간 초과. 설치와 공급자 상태를 확인하세요.") from error
    parts = []
    try:
        for line in result.stdout.splitlines():
            event = json.loads(line)
            if event["type"] == "error":
                error = event.get("error")
                if isinstance(error, dict) and error.get("type") == "provider.auth":
                    raise InvestigationError("OpenCode 공급자 인증이 거절됐습니다. 공급자에 다시 로그인하세요.")
                if isinstance(error, dict) and error.get("type") == "provider.quota":
                    raise InvestigationError("OpenCode 모델 사용량 또는 잔액 한도에 도달했습니다. 계정 한도와 --model 설정을 확인하세요.")
                raise InvestigationError("OpenCode가 조사 오류를 반환했습니다.")
            if event["type"] == "text":
                parts.append(event["part"]["text"])
        if result.returncode:
            raise InvestigationError("OpenCode 조사가 비정상 종료됐습니다.")
        return "".join(parts)
    except (ValueError, KeyError, TypeError, RecursionError) as error:
        raise InvestigationError("OpenCode 응답 형식이 예상과 다릅니다.") from error


def run_agent(investigation, model):
    tools = DISPOSAL_TOOLS
    instructions = AGENT_INSTRUCTIONS
    steps = investigation.max_pages + 5
    timeout = 120
    if investigation.a2a is not None:
        tools = [*tools, DELEGATE_TOOL]
        instructions += A2A_INSTRUCTIONS
        steps += 1
        timeout = 300
    answer = run_scoped_agent(
        investigation, model, agent=AGENT, instructions=instructions,
        tools=tools, steps=steps, prompt="선택된 폐기를 조사하세요.", timeout=timeout,
    )
    return investigation.validate_final(answer)


def run_metrics_agent(investigation, model):
    instructions = RETRY_METRICS_INSTRUCTIONS if investigation.handoff["status"] == "COMPLETED" else METRICS_INSTRUCTIONS
    answer = run_scoped_agent(
        investigation, model, agent=METRICS_AGENT, instructions=instructions,
        tools=METRICS_TOOLS, steps=7, prompt=json.dumps(investigation.handoff, ensure_ascii=False),
    )
    return investigation.validate_final(answer)


def run_retry_follow(gateway, disposal_id, max_pages, a2a, model, wait_seconds):
    def inspect(review):
        answer = run_scoped_agent(
            review, model, agent=AGENT, instructions=RETRY_INSTRUCTIONS, tools=RETRY_TOOLS,
            steps=8, prompt=f"{review.expected_status} 단계의 조회를 수행하세요.", timeout=180,
        )
        review.validate_final(answer)
        task_id, metrics, decision = review.metrics_task
        print(f"A2A 위임 완료 | {review.expected_status} | {task_id}")
        metrics.report(decision)
        return decision

    before = RetryReview(gateway, disposal_id, max_pages, a2a)
    initial = inspect(before)
    print(f"재시도 대기 | 동일 폐기 ID {disposal_id} | 최대 {wait_seconds}초", flush=True)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        status = before.read_detail()["status"]
        if status == "COMPLETED":
            break
        if status != "PENDING":
            raise InvestigationError(f"폐기 상태가 {status}로 확정됐습니다.")
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    else:
        raise InvestigationError("대기 시간 안에 COMPLETED 상태를 확인하지 못했습니다.")
    after = RetryReview(gateway, disposal_id, max_pages, a2a, before)
    completed = inspect(after)
    stock_before, stock_after = (review.inventory["onHandQuantity"] for review in (before, after))
    print(f"재시도 전후 | PENDING → COMPLETED | 현재고 {stock_before} → {stock_after} | "
          f"원장 {len(before.rows)}건 → {len(after.rows)}건")
    if all(after.comparison.values()) and before.match:
        print("판정 | 재고·원장 일치, 추가 차감 없음")
    elif all(after.comparison.values()):
        print("판정 | 요청 수량 1회 차감, 폐기 원장 1건 추가")
    else:
        print("판정 | 예상 재고·원장과 달라 차감 횟수 확인 불가")
    return int(not all(after.comparison.values()) or "insufficient" in (initial["assessment"], completed["assessment"]))


def main():
    parser = argparse.ArgumentParser(description="OpenCode가 읽기 전용 도구를 선택해 PENDING 폐기를 조사합니다.")
    parser.add_argument("disposal_id", metavar="DISPOSAL_ID", help="폐기 상세의 disposalId (UUID)")
    parser.add_argument("--port", type=bounded_int(1, 65535), default=7070, help="127.0.0.1의 Gateway 포트 (기본 7070)")
    parser.add_argument("--max-pages", type=bounded_int(1, 100), default=10, help="최대 원장 조회 페이지 (기본 10, 페이지당 100건)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"OpenCode provider/model (기본 {DEFAULT_MODEL})")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prometheus-port", type=bounded_int(1, 65535), nargs="?", const=9090,
                       help="로컬 Prometheus 협업 활성화 (127.0.0.1, 포트 생략 시 9090)")
    modes.add_argument("--a2a-port", type=bounded_int(1, 65535), nargs="?", const=8765,
                       help="Prometheus A2A 런타임에 위임 (127.0.0.1, 포트 생략 시 8765)")
    parser.add_argument("--follow-retry", type=bounded_int(1, 900), nargs="?", const=120, metavar="SECONDS",
                        help="재시도 전후를 A2A로 조회 (운영자 재시도 대기 기본 120초)")
    args = parser.parse_args()
    if args.follow_retry and args.a2a_port is None:
        parser.error("--follow-retry에는 --a2a-port가 필요합니다.")
    disposal_id = args.disposal_id.lower()
    if not DISPOSAL_ID.fullmatch(disposal_id):
        parser.error("DISPOSAL_ID는 하이픈이 포함된 UUID여야 합니다.")
    if not re.fullmatch(r"[\w.-]+/[\w./:#-]+", args.model):
        parser.error("--model은 OpenCode의 provider/model 형식이어야 합니다.")
    investigation = None
    result = 0
    try:
        a2a = MetricsA2AClient(args.a2a_port, a2a_access_token()) if args.a2a_port else None
        gateway = LoopbackReader(args.port, access_token())
        if args.follow_retry:
            return run_retry_follow(gateway, disposal_id, args.max_pages, a2a, args.model, args.follow_retry)
        investigation = Investigation(gateway, disposal_id, args.max_pages, a2a)
        decision = run_agent(investigation, args.model)
    except InvestigationError as error:
        records = investigation.evidence if investigation else []
        for item in records:
            source = f"원장 {item['page'] + 1}페이지 조회" if "page" in item else "폐기 상세 조회"
            print(f"근거 {item['evidenceId']} | {source}")
        print(f"판정 | 확인 불가\n근거 | {error}\n다음 조치 | 문제를 해결한 뒤 같은 폐기 ID로 다시 조회하세요.")
        decision = {"conclusion": "inconclusive", "evidence": [item["evidenceId"] for item in records]}
        result = 1
    else:
        investigation.report()
    if investigation and investigation.metrics_task:
        task_id, metrics, metrics_decision = investigation.metrics_task
        print(f"A2A 위임 완료 | {task_id}")
        metrics.report(metrics_decision)
        if metrics_decision["assessment"] == "insufficient":
            return 1
    if investigation and investigation.metrics_error:
        print(f"Prometheus A2A 조사 | 확인 불가\n근거 | {investigation.metrics_error}")
        return 1
    if args.prometheus_port and investigation and investigation.disposal and investigation.disposal["status"] == "PENDING":
        try:
            metrics = MetricsInvestigation(LoopbackReader(args.prometheus_port).get,
                                           investigation.disposal.get("createdAt"), decision)
            metrics_decision = run_metrics_agent(metrics, args.model)
            metrics.report(metrics_decision)
        except InvestigationError as error:
            print(f"Prometheus 장애 조사 | 확인 불가\n근거 | {error}")
            return 1
        if metrics_decision["assessment"] == "insufficient":
            return 1
    return result


if __name__ == "__main__":
    sys.exit(main())
