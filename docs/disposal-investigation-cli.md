# 폐기 PENDING 조사 에이전트

OpenCode 2가 폐기 상세와 재고 원장 조회 도구를 선택해 선택된 폐기 한 건을 조사한다.
로컬 Gateway가 기본 `127.0.0.1:7070`에서 실행 중이어야 한다.

```sh
python3 scripts/investigate_disposal.py 12345678-1234-4234-8234-123456789abc
```

예시 UUID를 실제 `disposalId`로 바꾸고, 숨김 프롬프트에 유효한 사용자 Access Token을 입력한다.
비대화식 실행에는 `ERPMSA_ACCESS_TOKEN` 환경변수를 제공한다.
다른 로컬 Gateway 포트는 `--port`, OpenCode 내장 카탈로그의 모델은 `--model provider/model`로 지정한다.
기본 모델은 `opencode/deepseek-v4.1-flash-free`다. OpenCode 공급자 인증이 필요하다.

## 인증과 사용량 제한

401 인증 오류가 표시되면 공식 Console 기기 인증을 다시 완료한다.

```sh
opencode auth login --standalone opencode
```

로그인 시 표시되는 브라우저 주소에서 기존 계정으로 인증한다.
429는 모델 사용량이나 계정 잔액 한도에 해당한다. 사용 가능한 모델은 `--model`로 지정한다.
예를 들어 `--model opencode/gpt-5.4-nano`는 Console 계정의 해당 모델 과금을 사용한다.

## 에이전트가 사용하는 도구

| 도구 | 허용된 조회 |
| --- | --- |
| `erp_get_disposal` | 실행 시 지정한 폐기 ID의 `GET /disposals/{disposalId}` |
| `erp_get_stock_movements` | 위 폐기의 식자재에 대한 `GET /foodmaterials/inventories/{foodMaterialId}/movements` 한 페이지 |

OpenCode가 조회 결과에 따라 다음 도구와 페이지를 선택한다. 상세가 `COMPLETED` 또는 `REJECTED`이면 조사 대상 여부를 판단해 종료한다.
`PENDING`이면 0페이지부터 원장을 조회하고, 대조 결과가 미확정이며 다음 페이지가 있으면 계속 조회할 수 있다.

CLI는 도구별 범위와 인자를 검증한다. 원장 조회는 100건씩 최대 10페이지가 기본이며 `--max-pages`로 1~100페이지를 지정한다.
전체 도구 호출은 최대 페이지 수에 3을 더한 횟수까지, 조사 실행은 모델 호출 120초까지 허용한다.
같은 상세나 이미 읽은 페이지는 메모리에 저장한 근거를 반환한다.

## Prometheus 장애 에이전트와 협업

```sh
python3 scripts/investigate_disposal.py 12345678-1234-4234-8234-123456789abc --prometheus-port 9090 --model opencode/gpt-5.4-nano
```

`--prometheus-port`를 지정하면 폐기 에이전트 다음에 별도 OpenCode 세션에서 장애 에이전트가 실행된다. 포트를 생략하면 루프백의 9090을 사용한다.
폐기 상세에서 `PENDING`을 확인하면 차감 대조 결론과 근거 번호를 인계한다. 원장 조회에 실패하면 `inconclusive`와 확보한 근거 번호를 전달한다.
장애 에이전트는 자기 세션에서 `erp_get_service_metric`으로 `scrape`, `http_5xx`, `p95_seconds`를 선택한다.
두 세션 모두 `--model`의 공급자 모델을 사용한다.

Prometheus 요청은 `GET /api/v1/query`로 제한한다. PromQL과 시각은 CLI가 결정한다.
Gateway·Disposals·FoodMaterials의 수집 상태 최솟값, HTTP 5xx 증가량 추정, p95 지연을 폐기 생성 시각 주변 5분 동안 조회한다.
조회 구간은 생성 2분 후 또는 현재 시각 중 먼저 도달한 시각에 끝난다.
요청 증가 표본이 없는 서비스의 5xx는 표본 없음으로 표시한다. p95는 수치로 보고한다.
장애 에이전트는 수집 실패·5xx 관측 여부와 인계받은 차감 결론을 사용해 다음 확인 대상을 고른다.
CLI는 양쪽 근거 번호와 다음 확인 대상이 조회 결과와 맞는지 검증한다. 지표 조회 실패와 표본 부족은 종료 코드 `1`로 표시한다. [Prometheus HTTP API](https://prometheus.io/docs/prometheus/latest/querying/api/)

## 별도 Prometheus 런타임에 A2A로 위임

같은 루프백 환경에서 두 프로세스에 공유 토큰을 전달한다. 아래 예시는 같은 셸에서 별도 프로세스를 띄운다.

```sh
export ERPMSA_A2A_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 scripts/serve_disposal_metrics.py --port 8765 --prometheus-port 9090 --model opencode/gpt-5.4-nano &
metrics_pid=$!
```

런타임 주소가 표시되면 폐기 조사 CLI를 실행한다.

```sh
python3 scripts/investigate_disposal.py 12345678-1234-4234-8234-123456789abc --a2a-port 8765 --model opencode/gpt-5.4-nano
```

폐기 에이전트가 `erp_delegate_prometheus`를 호출하면 CLI가 Agent Card를 확인하고 A2A 1.0 HTTP+JSON으로 조사 태스크를 생성한다.
런타임은 Prometheus 조회 결과와 근거 번호를 완료 태스크의 아티팩트로 반환한다.
폐기 에이전트는 전달받은 태스크 ID, 지표 판정, 근거 번호와 다음 확인 대상을 최종 답변에 반영한다.
위임 입력은 폐기 상태, 원장 대조 결론, 근거 번호, 조회 시각으로 제한한다. ERP 토큰과 폐기 식별자는 폐기 CLI가 보관한다.

지원 경로는 `GET /.well-known/agent-card.json`, `POST /message:send`, `GET /tasks/{id}`다.
태스크 생성·조회에는 A2A 전용 Bearer 토큰을 사용한다. ERP와 Prometheus에는 조회 `GET`만 보낸다.
런타임은 한 번에 조사 하나를 처리하고 최근 32개 태스크를 메모리에 보관한다. 같은 메시지 ID와 내용은 기존 태스크를 반환한다.
위임 실패는 원장 대조 결과와 함께 표시하며 종료 코드는 `1`이다. [A2A 1.0 사양](https://a2a-protocol.org/latest/specification/)

조사 런타임을 종료할 때는 같은 셸에서 `kill "$metrics_pid"`를 실행한다.

### 운영자 재시도 전후 추적

```sh
python3 scripts/investigate_disposal.py 12345678-1234-4234-8234-123456789abc \
  --a2a-port 8765 --follow-retry 120 --model opencode/gpt-5.4-nano
```

`PENDING` 건에서 시작한다. 폐기 에이전트는 현재고·전체 원장을 읽어 해당 폐기 원장 유무를 기록하고, 첫 A2A 조사 결과를 받은 뒤 `재시도 대기`를 표시한다. 운영자가 별도 채널에서 같은 폐기 ID를 재시도하면 CLI는 상세 `GET`으로 상태를 추적한다. 대기 시간 기본값은 120초이며 1~900초를 지정할 수 있다.

`COMPLETED`가 확인되면 폐기 에이전트가 같은 요청의 현재고·원장을 다시 읽고 완료 응답의 원장 ID·차감 후 수량을 실제 원장과 대조한다. 재시도 전 원장이 있었으면 두 시점의 현재고(버전 포함)와 원장 전체가 같아야 한다. 해당 원장이 없었으면 요청 수량만큼 차감되고 재고 버전이 한 단계 증가하며, 기존 원장에 해당 폐기 원장 한 건만 추가돼야 한다. 조회 도중 상태가 바뀌거나 전체 원장이 페이지 한도를 넘으면 확인 불가로 처리한다.

완료 단계의 A2A 태스크는 같은 `contextId`를 사용하고 재시도 전 태스크를 `referenceTaskIds`로 참조한다. Prometheus 에이전트는 재시도 전 원장 유무, 예상 재고·원장과의 일치 여부, 앞선 지표 판정을 바탕으로 완료 시각 주변 지표를 조회한다. 양쪽 에이전트의 업무·지표 요청은 `GET`으로 제한된다. 두 태스크를 같은 Prometheus 런타임에서 실행한다. [A2A 태스크와 맥락](https://a2a-protocol.org/latest/specification/#343-multi-turn-conversation-patterns)

## 근거와 판정

원장은 `DISPOSAL-{disposalId}`로 찾고 유형, 식자재, 수량, 사유를 코드로 대조한다.
도구는 상태, 페이지, 대조 결과와 `E1` 같은 근거 참조를 반환한다.
모델은 이 결과를 근거로 결론과 근거 참조를 제출하며, CLI가 실제 조회 결과와 대조한 뒤 보고서를 출력한다.

| 판정 | 근거와 다음 조치 |
| --- | --- |
| 재고 차감 원장 확인 | 일치한 원장 ID와 차감 전후 수량을 표시한다. 현재 상태가 여전히 `PENDING`이면 운영자가 동일 폐기 ID의 기존 재시도 API를 사용할 수 있다. |
| 해당 키를 찾지 못함 | 전체 페이지를 읽었지만 해당 키가 없었다. 서로 다른 조회 시점 때문에 차감 여부는 미확정이다. 서비스 상태와 현재 폐기 상태를 확인한다. |
| 확인 불가 | 조회 실패, 한도 도달, 내용 불일치, 근거 부족 또는 모델 결론 검증 실패가 발생했다. 원인을 해결한 뒤 같은 폐기 ID로 다시 조회한다. |
| 조사 대상 아님 | `COMPLETED` 또는 `REJECTED` 상태를 표시한다. |

종료 코드는 검증된 보고서 출력 `0`, 확인 불가 `1`, CLI 인자 오류 `2`다.
에이전트의 조회가 생략되거나 중간에 끝나면 근거 부족으로 처리한다.

## 실행 경계

ERP HTTP 요청은 두 API의 `GET`으로 고정한다. 폐기 ID와 식자재 ID는 CLI가 결정한다.
모델은 원장 페이지 번호만 지정할 수 있으며, 상세 조회가 선행되어야 한다.
폐기 세션에는 폐기 상세·원장 도구를 허용하고 장애 세션에는 지표 도구만 허용한다.
ERP 토큰은 CLI 프로세스에 보관하고, 모델에는 상태·페이지·대조 결과만 전달한다. ID, 수량, 사유 원문은 로컬 보고서에서 관리한다.
Prometheus 요청에는 ERP 토큰을 전달하지 않는다. 장애 세션의 모델에는 허용된 서비스 이름, 지표 수치와 근거 번호를 전달한다.

실행할 때 임시 MCP 엔드포인트와 인증된 OpenCode 서버를 루프백에 띄우고, 종료 시 프로세스와 임시 설정을 정리한다.
모델에 전달할 도구가 준비된 뒤 조사를 시작한다. OpenCode 2.0.18의 연결 후 도구 등록 지연을 반영했다.
연동 형식과 권한 규칙은 [OpenCode MCP 문서](https://dev.opencode.ai/docs/mcp-servers/)와 [권한 문서](https://dev.opencode.ai/docs/permissions/)를 따른다.

## 검증

### 두 동시 재시도 시나리오 통합 실행

`scripts/verify-disposal-concurrent-retries.py`는 차감 전 `PENDING`과 차감 후 응답 유실 `PENDING`을 순서대로 실행한다. 각 사례마다 이관 검증 JSON의 백업·이력 해시를 확인하고 별도 임시 MySQL, Gateway·FoodMaterials·Disposals, Prometheus를 루프백에 띄운다. 기존 서비스의 접속 설정이나 Docker 볼륨은 사용하지 않는다.

Python 3, Java 21, MySQL 8.0 클라이언트·서버, Prometheus, OpenSSL, 모델 인증이 완료된 OpenCode가 필요하다. Gateway·FoodMaterials·Disposals의 `bootJar`를 준비한다. MySQL 바이너리가 `/usr/local/mysql/bin` 밖에 있으면 `--mysql-bin-dir`을 지정한다. `--prometheus`에는 프로젝트 이미지와 같은 버전의 실행 파일을 지정할 수 있다.

```sh
python3 scripts/verify-disposal-concurrent-retries.py \
  --backup /path/to/legacy-backup.sql.gz \
  --migration-report .verification/legacy-disposal/actual-migration-20261109.json \
  --prometheus /path/to/prometheus \
  --report ".verification/disposal-agent/a2a-concurrent-retries-$(date +%Y%m%d-%H%M%S).json"
```

각 사례에서 스크립트가 같은 폐기 ID로 `POST` 두 건을 동시에 보낸다. 폐기 행 잠금 대기, 두 `200 COMPLETED`의 같은 원장 ID, 예상 재고·원장 변화를 대조한다. 실제 모델은 재시도 전후에 `GET`으로 조회하고 완료 A2A 태스크가 같은 맥락에서 이전 태스크를 참조하는지 확인한다. 결과는 두 사례를 담은 새 JSON 하나에 기록하며, 둘 다 통과했을 때 종료 코드는 `0`이다.

### Jenkins에서 수동 실행

`erpmsa-disposal-live` 라벨을 가진 실행 노드 하나에 위 검증에 필요한 도구와 JAR를 준비한다. OpenCode는 Jenkins 실행 계정에서 실제 모델을 호출할 수 있어야 한다.

| 노드 환경 변수 | 값 |
| --- | --- |
| `ERPMSA_DISPOSAL_REPO` | 검증 스크립트와 서비스 JAR가 준비된 ErpMSA 체크아웃 절대 경로 |
| `ERPMSA_DISPOSAL_BACKUP` | 읽기 전용 레거시 백업 절대 경로 |
| `ERPMSA_DISPOSAL_MIGRATION_REPORT` | 백업·이력 해시를 담은 이관 검증 JSON 절대 경로 |
| `ERPMSA_DISPOSAL_MYSQL_BIN_DIR` | 선택 사항. 기본값 `/usr/local/mysql/bin` |
| `ERPMSA_DISPOSAL_PROMETHEUS` | 선택 사항. 기본값 `prometheus` |
| `ERPMSA_DISPOSAL_MODEL` | 선택 사항. 기본값 `opencode/gpt-5.4-nano` |

접근이 허용된 IP에서 Jenkins HTTPS 주소로 다음 명령을 실행한다. 인증 파일은 `username:api-token` 한 줄을 담은 권한 `600` 파일이다. Jenkins 계정에는 노드와 Job 조회, 새 Job 생성, 빌드 실행 권한이 필요하다. [Jenkins Remote Access API](https://www.jenkins.io/doc/book/using/remote-access-api/)

```sh
python3 scripts/run-jenkins-disposal-retries.py \
  --url "$JENKINS_URL" \
  --auth-file /secure/jenkins-api-token \
  --job-name disposal-concurrent-retries \
  --output ./disposal-concurrent-retries.json
```

스크립트는 Job 이름이 비어 있는지와 노드의 라벨·온라인 상태·실행기 수를 확인하고, `jenkins/disposal-concurrent-retries-job.xml`로 새 Job을 등록한다. 도구와 파일 경로는 실제 Job을 실행하는 노드에서 점검한다. 등록 없이 노드와 Job 이름만 확인하려면 `--check-only`를 사용한다.

수동 실행의 큐 ID로 해당 빌드만 추적하고 아티팩트 `artifacts/disposal-concurrent-retries.json`을 새 로컬 파일로 저장한다. JSON을 생성한 실패 실행의 결과도 저장하며 종료 코드는 `1`이다. 기존 Job 이름이나 출력 파일 경로는 거절한다. 대기 시간이 초과되면 출력된 큐·빌드 주소에서 상태를 확인한다. 등록된 Job을 다시 실행할 때는 Jenkins 화면의 **Build Now**를 사용한다.

### 조회 도구 회귀 검증

```sh
python3 -m unittest discover -s scripts -p 'test_investigate_disposal.py' -v
ERPMSA_TEST_OPENCODE=1 python3 -m unittest discover -s scripts -p 'test_investigate_disposal.py' -v
ERPMSA_TEST_LIVE_MODEL=opencode/gpt-5.4-nano python3 -m unittest discover -s scripts -p 'test_investigate_disposal.py' -k live_model -v
python3 -m unittest discover -s scripts -p 'test_disposal_a2a.py' -v
```

첫 명령은 테스트용 OpenCode 실행 파일과 루프백 ERP HTTP 서버로 동작과 호출 제한을 검증한다.
둘째 명령은 실제 OpenCode 2와 스크립트로 응답하는 테스트 공급자를 추가로 사용해 MCP 도구 호출 왕복을 검증한다.
실제 OpenCode 검증은 로컬 테스트 공급자와 임시 데이터 디렉터리를 사용한다.
셋째 명령은 실제 공급자 모델로 폐기 조회와 장애 에이전트의 근거 인계를 검증하며 모델 사용량이 발생한다.
넷째 명령은 A2A 위임의 인증, 조회 범위, 중복 요청 처리와 결과 대조를 검증한다.

2026-11-09에는 `opencode/gpt-5.4-nano`로 기존 Disposals·FoodMaterials JAR를 임시 MariaDB와 연결해 세 사례를 검증했다.
차감 원장 확인, 원장 미발견, 두 번째 페이지에서 차감 원장 확인에 각각 GET 2건, 2건, 3건을 사용했다.
서비스 DB 계정은 조사 중 SELECT 권한만 가졌으며, 폐기·현재고·재고 원장의 전후 스냅샷 해시가 일치했다.
테스트는 Gateway 대신 임시 루프백 라우터로 Spring API에 연결했다.

멀티에이전트 검증에서는 `opencode/gpt-5.4-nano` 세션 두 개를 테스트 ERP 응답과 합성 시계열을 넣은 임시 Prometheus에 연결했다.
같은 장애 지표에서 차감 원장이 확인된 경우에는 상태 확정 구간을, 원장을 찾지 못한 경우에는 식자재 서비스로 보낸 차감 요청을 다음 확인 대상으로 골랐다.
두 사례에서 ERP `GET` 4건, Prometheus 지표 `GET` 6건을 확인했다.
