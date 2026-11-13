"""Prometheus evidence for the service window around a scoped disposal."""

from datetime import datetime, timezone
import json
import math
import time
from urllib.parse import urlencode

from disposal_mcp import InvestigationError


METRICS_AGENT = "erp-prometheus-investigator"
JOBS = ("gateway-server", "disposals-service", "foodmaterials-service")
SELECTOR = 'job=~"' + "|".join(JOBS) + '"'
REQUEST_COUNT = "http_server_requests_seconds_count"
TRAFFIC = f"sum by (job) (increase({REQUEST_COUNT}{{{SELECTOR}}}[5m])) > 0"
QUERIES = {
    "scrape": f"min by (job) (min_over_time(up{{{SELECTOR}}}[5m]))",
    "http_5xx": (
        f'(sum by (job) (increase({REQUEST_COUNT}{{{SELECTOR},status=~"5.."}}[5m])) '
        f"or on (job) 0 * ({TRAFFIC})) and on (job) ({TRAFFIC})"
    ),
    "p95_seconds": (
        f"histogram_quantile(0.95, sum by (le, job) "
        f"(rate(http_server_requests_seconds_bucket{{{SELECTOR}}}[5m])))"
    ),
}
METRIC_LABELS = {"scrape": "수집 상태 최솟값", "http_5xx": "HTTP 5xx 증가량 추정", "p95_seconds": "p95 지연(초)"}
METRICS_TOOLS = [{
    "name": "get_service_metric",
    "description": "지정된 5분 구간의 서비스 수집 상태, HTTP 5xx 또는 p95 지연을 조회한다.",
    "inputSchema": {
        "type": "object", "properties": {"metric": {"type": "string", "enum": list(QUERIES)}},
        "required": ["metric"], "additionalProperties": False,
    },
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
}]
METRICS_INSTRUCTIONS = """
사용자 메시지의 JSON은 폐기 에이전트가 전달한 검증된 조회 근거다.
erp_get_service_metric으로 scrape, http_5xx, p95_seconds를 각각 조회한다. 조회 순서는 자유다.
서비스 지표는 서비스 단위 관측으로 해석한다. 폐기 차감 판정은 전달받은 결론을 그대로 사용한다.
조회 오류가 있으면 중단한다. 세 지표 조회 후 다른 글이나 마크다운 없이 아래 형식의 JSON을 출력한다.
{"assessment":"마지막 도구 응답의 assessment","evidence":["P1","P2","P3"],"disposalConclusion":"전달받은 disposalConclusion","disposalEvidence":["전달받은 배열의 항목들"],"nextCheck":"아래 규칙으로 선택한 값"}
evidence에는 실제 지표 근거 번호를 발급 순서대로 넣고, disposalEvidence에는 전달받은 배열을 그대로 넣는다.
nextCheck는 다음 규칙으로 선택한다.
- signals_observed와 matched면 trace_disposal_result, 그 밖의 signals_observed면 trace_stock_call.
- insufficient면 verify_metric_coverage.
- no_down_or_5xx와 matched면 review_disposal_state, 그 밖의 no_down_or_5xx면 review_stock_history.
"""
RETRY_METRICS_INSTRUCTIONS = """
같은 폐기 건의 재시도 완료 시점 지표를 조사한다.
erp_get_service_metric으로 scrape, http_5xx, p95_seconds를 각각 한 번 조회한다. 조회 오류가 있으면 중단한다.
stockComparison은 재시도 후 예상 재고·원장과의 일치 여부다. previousDisposalConclusion이 matched면 변화 없음,
no_match면 요청 수량의 차감 한 번과 해당 폐기 원장 한 건 추가가 예상 결과다.
세 번째 도구 응답의 decision 객체 전체를 최종 답변으로 출력한다.
decision 안에는 assessment, evidence, disposalConclusion, disposalEvidence, stockComparison,
previousAssessment, previousDisposalConclusion, nextCheck가 있다. 바깥에 decision 키를 추가하지 않는다.
마크다운과 설명 없이 JSON 객체만 출력한다.
"""


def metric_values(payload, metric):
    data = payload.get("data")
    if (payload.get("status") != "success" or payload.get("warnings") or not isinstance(data, dict)
            or data.get("resultType") != "vector" or not isinstance(data.get("result"), list)):
        raise InvestigationError("Prometheus 응답에서 완전한 벡터를 확인하지 못했습니다.")
    values = {}
    for row in data["result"]:
        if not isinstance(row, dict) or not isinstance(row.get("metric"), dict):
            raise InvestigationError("Prometheus 시계열 형식이 예상과 다릅니다.")
        job = row["metric"].get("job")
        sample = row.get("value")
        if (job not in JOBS or job in values or not isinstance(sample, list)
                or len(sample) != 2 or not isinstance(sample[1], str)):
            raise InvestigationError("Prometheus 시계열의 대상 또는 샘플 형식이 예상과 다릅니다.")
        try:
            value = float(sample[1])
        except ValueError as error:
            raise InvestigationError("Prometheus 샘플을 숫자로 읽을 수 없습니다.") from error
        if value < 0 or (metric == "scrape" and value not in (0, 1)):
            raise InvestigationError("Prometheus 샘플 값이 지표 범위를 벗어났습니다.")
        values[job] = value if math.isfinite(value) else None
    return {job: values.get(job) for job in JOBS}


class MetricsInvestigation:
    def __init__(self, get, created_at, decision, *, window_end=None, retry=None):
        try:
            created = datetime.fromisoformat(created_at)
            now = time.time()
            if created.tzinfo is None or created.timestamp() > now:
                raise ValueError()
            self.end = min(created.timestamp() + 120, now)
            if window_end is not None:
                if type(window_end) not in (int, float) or not created.timestamp() <= window_end <= self.end:
                    raise ValueError()
                self.end = window_end
        except (TypeError, ValueError, OverflowError, OSError) as error:
            raise InvestigationError("폐기 상태의 시각을 확인할 수 없어 지표 조회 구간을 정하지 못했습니다.") from error
        self.get = get
        self.handoff = {"status": "PENDING", "disposalConclusion": decision["conclusion"],
                        "disposalEvidence": decision["evidence"]}
        if retry is not None:
            self.handoff.update(status="COMPLETED", **retry)
        self.evidence = {}
        self.calls = 0
        self.failure = None

    def call(self, name, arguments):
        self.calls += 1
        if self.failure:
            return {"error": self.failure}
        try:
            if self.calls > 5:
                raise InvestigationError("Prometheus 도구 호출 한도에 도달했습니다.")
            if name != "get_service_metric" or not isinstance(arguments, dict) or set(arguments) != {"metric"}:
                raise InvestigationError("허용된 지표 조회 도구와 인자만 사용할 수 있습니다.")
            metric = arguments["metric"]
            if not isinstance(metric, str) or metric not in QUERIES:
                raise InvestigationError("허용된 Prometheus 지표 이름을 사용하세요.")
            if metric not in self.evidence:
                query = urlencode({"query": QUERIES[metric], "time": self.end, "timeout": "2s"})
                payload = self.get(f"/api/v1/query?{query}", "Prometheus")
                self.evidence[metric] = {"evidenceId": f"P{len(self.evidence) + 1}", "metric": metric,
                                         "values": metric_values(payload, metric)}
            result = self.evidence[metric]
            if len(self.evidence) == len(QUERIES):
                if self.handoff["status"] == "COMPLETED":
                    return {**result, "decision": self.decision()}
                return {**result, "assessment": self.assessment()}
            return result
        except InvestigationError as error:
            self.failure = str(error)
            return {"error": self.failure}

    def assessment(self):
        scrape = self.evidence["scrape"]["values"].values()
        errors = self.evidence["http_5xx"]["values"].values()
        if 0 in scrape or any(value is not None and value > 0 for value in errors):
            return "signals_observed"
        if None in scrape or None in errors:
            return "insufficient"
        return "no_down_or_5xx"

    def decision(self):
        assessment = self.assessment()
        matched = self.handoff["disposalConclusion"] == "matched"
        next_check = {
            "signals_observed": "trace_disposal_result" if matched else "trace_stock_call",
            "insufficient": "verify_metric_coverage",
            "no_down_or_5xx": "review_disposal_state" if matched else "review_stock_history",
        }
        expected = {
            "assessment": assessment, "evidence": [item["evidenceId"] for item in self.evidence.values()],
            "disposalConclusion": self.handoff["disposalConclusion"], "disposalEvidence": self.handoff["disposalEvidence"],
            "nextCheck": next_check[assessment],
        }
        if self.handoff["status"] == "COMPLETED":
            comparison = self.handoff["stockComparison"]
            next_check = {"insufficient": "verify_metric_coverage", "signals_observed": "review_retry_signals",
                          "no_down_or_5xx": "retry_verified"}
            expected.update(stockComparison=comparison, previousAssessment=self.handoff["previousAssessment"],
                            previousDisposalConclusion=self.handoff["previousDisposalConclusion"],
                            nextCheck=next_check[assessment] if all(comparison.values()) else "review_retry_evidence")
        return expected

    def validate_final(self, answer):
        if self.failure:
            raise InvestigationError(self.failure)
        if len(self.evidence) != len(QUERIES):
            raise InvestigationError("장애 에이전트가 세 지표 조회를 완료하지 못했습니다.")
        try:
            result = json.loads(answer)
        except (ValueError, RecursionError) as error:
            raise InvestigationError("장애 에이전트의 최종 결론을 해석할 수 없습니다.") from error
        if result != self.decision():
            raise InvestigationError("장애 에이전트의 결론 또는 전달 근거가 실제 조회 결과와 일치하지 않습니다.")
        return result

    def report(self, decision):
        start = datetime.fromtimestamp(self.end - 300, timezone.utc).isoformat(timespec="seconds")
        end = datetime.fromtimestamp(self.end, timezone.utc).isoformat(timespec="seconds")
        phase = "재시도 완료" if self.handoff["status"] == "COMPLETED" else "폐기 생성"
        print(f"Prometheus 장애 조사 | {phase} 시각 주변 {start} ~ {end}")
        print(f"협업 근거 | 폐기 에이전트의 {', '.join(decision['disposalEvidence'])} 인계 확인")
        for item in self.evidence.values():
            values = ", ".join(f"{job}={value:.6g}" if value is not None else f"{job}=표본 없음"
                               for job, value in item["values"].items())
            print(f"근거 {item['evidenceId']} | {METRIC_LABELS[item['metric']]} | {values}")
        label = {"signals_observed": "수집 실패 또는 HTTP 5xx 관측", "insufficient": "표본 부족",
                 "no_down_or_5xx": "조회 구간에 수집 실패·HTTP 5xx 미관측"}
        print(f"장애 판정 | {label[decision['assessment']]}")
        next_check = {
            "trace_disposal_result": "차감 결과 응답부터 폐기 상태 확정까지의 요청 로그나 트레이스를 확인하세요.",
            "trace_stock_call": "폐기 서비스가 식자재 서비스로 보낸 차감 요청의 로그나 트레이스를 확인하세요.",
            "verify_metric_coverage": "해당 시각의 대상 수집 범위와 HTTP 요청 표본을 확인하세요.",
            "review_disposal_state": "같은 폐기 ID의 최신 상태와 처리 로그를 확인하세요.",
            "review_stock_history": "같은 폐기 ID의 재고 원장과 요청 로그를 다시 확인하세요.",
            "review_retry_evidence": "재시도 전후 재고·원장 차이를 확인하세요.",
            "review_retry_signals": "재시도 구간에 관측된 서비스 장애 신호를 확인하세요.",
            "retry_verified": (
                "요청 수량이 한 번 차감되고 폐기 원장이 한 건 추가됐습니다."
                if self.handoff.get("previousDisposalConclusion") == "no_match"
                else "재시도 전후 재고와 원장이 일치합니다."
            ),
        }
        print(f"다음 확인 | {next_check[decision['nextCheck']]}")
        print("해석 | Prometheus 수치는 서비스 단위 관측입니다.")
