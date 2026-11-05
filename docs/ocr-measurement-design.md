# OCR 속도·정확도 측정 설계

대상은 별도 프로젝트 `~/Desktop/ocrserver`(FastAPI + Surya OCR 2, llama.cpp GGUF)의
`POST /api/v1/business-document-ocr`다. ErpMSA 저장소에는 OCR 구현이 없고 AccountService의
`document_path`·`ocr_confidence` 컬럼만 있다. 이 문서는 측정 방법과 2026-11-02 전후 비교 결과를 기록하며, AccountService 연동이나
ocrserver를 ErpMSA Compose에 추가하는 것은 범위에 포함하지 않는다.

## 1. 현재 상태

| 항목 | 상태 |
|---|---|
| OCR 응답 필드 | `status`(AUTO_ACCEPTED / REVIEW_REQUIRED / NOT_FOUND), `businessRegistrationNumber`(AUTO_ACCEPTED일 때만), `companyName`, `representativeName`, `validityStartDate`, `validityEndDate`, `candidates[]` |
| 처리 단계 | 이미지 로딩 → 1차 전체 페이지 추론 → (자동승인 아니면) 키워드 블록 2차 재인식 |
| 단계별 시간 | `logs/app.log`에 `⏱️` 로그로만 남음. 지표(`/metrics`) 없음 |
| 평가 데이터셋 | `eval/dataset/`: 확정 라벨 41건(실제 확인서 1건 + 소상공인 합성 40건), 2.3절 참조 |
| `~/Downloads/*_TextOCR_*.json` | 다른 OCR 엔진의 인식 결과(V2 형식)다. 비교 기준선은 될 수 있으나 정답 라벨이 아니다 |
| Jenkins | ErpMSA 파이프라인만 있음. 플러그인은 pipeline·git·docker·credentials뿐 |
| Grafana | Pushgateway의 오프라인 측정 결과를 Prometheus로 수집. `erpmsa-ocr-benchmark`에서 Before/After 비교 |

### 1.1 기존 로그에서 본 참고값 (측정 결과로 쓰지 않음)

`logs/app.log`(2026-06-12 ~ 07-03)의 OCR 요청 72건을 집계했다.

- 응답 0.001~0.002초, 사업자번호 `1234567891` 고정인 19건은 실제 추론이 아닌 대체 서비스 응답이다. 제외했다.
- 실제 추론으로 보이는 200 응답 53건: p50 8.72s, p90 13.16s, p95 13.90s, 최대 29.30s, 평균 9.58s.
- 단계별 평균(31건): 이미지 로딩 0.01s, 1차 추론 9.59s(최대 29.27s), 2차 재인식 0.49s. 지연은 대부분 1차 추론이다.
- 500 `OCR_PROCESSING_FAILED` 2건.

같은 파일을 반복해 올렸고, 개발 서버 재시작·코드 변경·실행 환경이 섞여 있어 통제된 측정이 아니다.
정답이 없으므로 정확도는 산출할 수 없다. 아래 벤치마크로 다시 측정한다.

### 1.2 통제된 Before/After 측정 (2026-11-02)

아래 표는 15:55~16:13의 최초 비교 결과다. 준비 상태 점검을 수정한 후속 실행은 8.9절에 따로 기록한다.

합성 사업자등록증 30건·소상공인 확인서 10건과 실제 확인서 `s001` 1건을 같은 순서로 측정했다.
두 환경 모두 동시성 1, 콜드 1회, 워밍업 3회 제외, 문서당 1회다. 이전 1건짜리 도구 확인 결과와 옛 합성 데이터 결과는 비교에서 제외했다.

| 항목 | Before `before-local-q8` | After `after-modal-l4` |
|---|---|---|
| 환경 | Mac Metal, Q8_0 | Modal 테스트 앱, L4, 원본 GGUF |
| 웜 p50 / p95 / 최대 (각 n=41) | 6.75s / 10.10s / 130.05s | 4.28s / 5.40s / 6.88s |
| 콜드 (각 n=1) | 19.67s | 158.71s, 새 컨테이너·L4 배정 대기 확인 |
| 자동승인 정밀도 | 100% (7/7) | 100% (7/7) |
| 자동승인율 / 후보 재현율 | 17.07% (7/41) / 97.56% (40/41) | 17.07% (7/41) / 97.56% (40/41) |
| 상호 / 대표자 일치율 | 85.37% (35/41) / 90.24% (37/41) | 85.37% (35/41) / 92.68% (38/41) |
| 실제 1건: 후보 / 상호 / 대표자 일치 | 0/1 / 0/1 / 1/1 | 0/1 / 0/1 / 1/1 |
| 합성 40건: 후보 / 상호 / 대표자 일치 **(실제보다 높게 나올 수 있음)** | 40/40 / 35/40 / 36/40 | 40/40 / 35/40 / 37/40 |
| 웜 처리 실패 / 콜드 실패 | 0/41 / 0/1 | 0/41 / 0/1 |
| 백엔드 준비 상태 검사 | PASS (`llamacpp`) | FAIL (`/health/ready` 503), 추론 기동은 로그로 확인 |

이 표본에서 After의 웜 지연은 Before 대비 p50 기준 1.58배, p95 기준 1.87배 개선됐다.
콜드 지연은 반대로 8.07배 길었다. 하드웨어·양자화·네트워크가 함께 달라져 원인별 효과로 분리할 수 없다.
실제 서류는 1건뿐이고 합성 서류 비중이 높으므로 운영 정확도로 일반화하지 않는다. 상세 근거와 제한은 8.5~8.8절에 기록했다.

## 2. 데이터셋

### 2.1 위치와 보안

- 실제 사업자 서류에는 상호·대표자 성명 등 개인정보가 있다. 이미지와 라벨은 Git에 넣지 않는다.
- 위치: `ocrserver/eval/dataset/`(gitignore). Jenkins에는 경로만 파라미터로 넘기거나 Jenkins 호스트의 읽기 전용 마운트로 제공한다.
- 결과 보고서에는 파일 ID와 통계만 남기고, 인식된 원문은 남기지 않는다(오류 분석용 상세 결과는 로컬에만 저장).

### 2.2 라벨 형식 `labels.jsonl`

한 줄에 문서 하나. 문서에 없는 필드는 `null`(빈 문자열 아님)로 둔다.

```json
{"id":"s001","file":"images/s001.jpg","docType":"BUSINESS_REGISTRATION","businessRegistrationNumber":"1234567891","companyName":"김밥천국","representativeName":"홍길동","validityStartDate":null,"validityEndDate":null,"tags":["photo","rotated"],"verified":true}
```

- `docType`: `BUSINESS_REGISTRATION`(사업자등록증), `SME_CONFIRMATION`(중소기업 확인서), `OTHER`. 종류별로 따로 집계한다.
- `verified`: 사람이 원본과 대조해 확정했으면 `true`. 벤치마크는 `true`인 라벨만 정확도에 반영한다.
- 정답 번호가 체크섬에 맞지 않는 테스트 서류(`invalid-checksum` 태그)는 자동승인되지 않는 것이 정상이다.
  이 경우 `REVIEW_REQUIRED`이면서 후보에 정답이 있으면 맞은 것으로 본다.
- 도구: `ocrserver/eval/labels.py`(`init`, `check`). 형식·파일 존재·중복·날짜 순서를 검사한다.
- `tags`: 촬영/스캔, 회전, 저해상도, PDF 여부 등 조건. 조건별 정확도 비교에 쓴다.
- 날짜는 `YYYY-MM-DD`, 사업자번호는 숫자 10자리로 저장한다.
- 라벨은 사람이 원본을 보고 작성한다. OCR 결과를 고쳐 쓰면 OCR 오류가 정답에 남을 수 있다.

### 2.3 규모

- 정확도 비율의 오차를 줄이려면 서류 종류별로 최소 30장, 가능하면 100장 이상이 필요하다.
- 30장 미만일 때는 비율과 함께 건수(예: 27/30)를 반드시 같이 적는다.

이번 비교는 소상공인(개인사업자) 합성 40건과 기존 실제 확인서 `s001` 1건, 총 41건이다.
`syn-7-*` 라벨·이미지 40건만 제거하고 `eval.synth --count 40 --seed 11`로 `syn-11-000`~`syn-11-039`를 생성했다.
기존 실제 이미지와 라벨 값은 유지했다. 합성 생성기와 추출기는 수정하지 않았다.

| 합성 구성 | 건수 |
|---|---:|
| 개인사업자 사업자등록증 | 30 (일반과세자 10, 간이과세자 20) |
| 소기업(소상공인) 확인서 | 10 |
| 법인 | 0 |
| scan / photo / blur / lowres | 각 10 |
| 체크섬 오류 번호 | 7 (사업자등록증 4, 확인서 3) |

실제 `s001`도 체크섬 오류 번호이므로 전체 체크섬 오류는 8건이다. 41건 모두 `verified: true`이며 라벨 검사를 통과했다.
`syn-11-000`, `001`, `003`, `007` 이미지를 직접 열어 사업자등록증·확인서 표기와 scan/photo/lowres 렌더링을 확인했다.
합성 확인서의 유효기간은 생성기 값 그대로 사용했다. 기간의 현재 유효성이나 가입 심사 적격 여부는 이 OCR 평가 대상이 아니다.

라벨 SHA-256: `c6d42e95509e09dac19415892fcde03595eaa424d350334e507b89838c1d2397`.
측정 전후 라벨 및 41개 이미지 해시와 처리 순서가 동일한지 대조했다. 실제 이미지는 Git에 추가하지 않았다.

## 3. 정확도 지표

### 3.1 사업자등록번호 (핵심 지표)

문서마다 결과를 아래 하나로 분류한다.

| 분류 | 조건 |
|---|---|
| A. 자동승인·정답 | `AUTO_ACCEPTED` 이고 번호 = 정답 |
| B. 자동승인·오답 | `AUTO_ACCEPTED` 이고 번호 ≠ 정답 (가장 위험) |
| C. 검토필요·후보에 정답 있음 | `REVIEW_REQUIRED` 이고 `candidates`에 정답 포함 |
| D. 검토필요·후보에 정답 없음 | `REVIEW_REQUIRED` 이고 정답이 후보에 없음 |
| E. 미검출 | `NOT_FOUND` |
| F. 처리 실패 | HTTP 4xx/5xx, 시간 초과 |

산출 지표:

- **자동승인 정밀도** = A / (A + B). 목표 100%. B가 1건이라도 나오면 실패로 표시한다.
- **자동승인율** = (A + B) / 전체. 사람 검토 없이 처리되는 비율.
- **후보 재현율** = (A + C) / 전체. 검토 화면에서 정답을 고를 수 있는 비율.
- **처리 실패율** = F / 전체.

`score`·`confidence`는 엔진·추출기가 매긴 값이며 정확도가 아니다. 대신 score 구간별 정답률을 표로 만들어,
현재 자동승인 임계값(`auto_accept_threshold=0.82`, `minimum_score_gap=0.10`)이 적절한지 확인한다.

### 3.2 텍스트 필드 (`companyName`, `representativeName`)

- **정확 일치율**: 정규화 후 완전 일치. 정규화는 앞뒤 공백 제거, 연속 공백 1개로 축소, 전각→반각만 한다.
  `(주)`↔`주식회사` 같은 의미 치환은 하지 않고, 필요하면 별도 지표로 둔다.
- **문자 오류율(CER)**: 편집 거리 / 정답 길이. 부분적으로 맞은 정도를 본다.
- 정답이 `null`인데 값을 낸 경우는 오검출, 정답이 있는데 `null`이면 누락으로 따로 센다.

### 3.3 날짜 필드 (`validityStartDate`, `validityEndDate`)

- `YYYY-MM-DD`로 정규화 후 정확 일치율. 오검출·누락은 3.2와 같이 센다.

## 4. 속도 지표

### 4.1 측정 방식

- 벤치마크 클라이언트가 HTTP 요청 전후를 `time.perf_counter()`로 잰다(종단 지연).
- 서버 단계별 시간(로딩 / 1차 / 2차)은 응답 헤더 또는 디버그 필드로 내려주도록 ocrserver를 수정해 같은 요청에 묶는다.
  로그 파싱은 동시 요청 시 섞이므로 쓰지 않는다.
- 시작 직후 첫 요청은 모델 로드가 포함되므로 **콜드 스타트**로 따로 기록하고, 이후 워밍업 3건은 버린다.
- 각 문서를 3회 반복하고, 동시성 1(현재 `SURYA_INFERENCE_PARALLEL=1`)로 측정한다.
  동시성 2·4 측정은 큐 대기 시간을 보는 별도 실험으로 나눈다.

위 반복 3회는 확장 측정 설계다. 이번 인계 작업의 비교는 두 환경 모두 `--cold-runs 1 --warmup 3 --repeats 1`로 실행했다.

### 4.2 보고 값

- 종단 지연 p50 / p90 / p95 / 최대, 콜드 스타트 시간.
- 단계별 p50 / p95, 2차 재인식이 실행된 비율.
- 페이지 수·이미지 해상도·`tags`별 지연.
- 1분당 처리 문서 수(동시성 1 기준).

### 4.3 실행 환경 기록

결과는 실행 환경에 따라 크게 달라지므로 결과 파일에 반드시 남긴다.

- 추론 백엔드(`/health/ready`의 `backend`), llama.cpp 바이너리, GGUF 파일명·크기, GPU/Metal/CPU 여부
- 실행 위치(로컬 Mac / Modal GPU 종류), ocrserver 코드 버전
- `backend`가 실제 Surya가 아니면 벤치마크를 중단한다(1.1의 대체 응답이 섞이는 것을 방지).

현재 도구는 측정 후 `/health/ready`를 검사한다. 최초 Modal 실행은 준비 상태 URL 결함 때문에 검사가 FAIL이며,
검사를 통과한 것으로 바꾸지 않았다. 새 컨테이너의 모델 경로·llama-server 기동 로그를 보조 근거로 남겼다(8.8절).

## 5. 실행 구조

```text
eval/dataset/labels.jsonl + images
          │
          ▼
eval/benchmark.py ──HTTP──▶ ocrserver (로컬 llama.cpp 또는 Modal)
          │
          ├─ results/<run-id>/summary.json   전체 지표 + 환경
          ├─ results/<run-id>/per-file.csv   문서별 분류·지연 (원문 제외)
          └─ results/<run-id>/junit.xml      임계값 검사 결과
```

- 추론은 Jenkins 컨테이너 안에서 하지 않는다. Jenkins는 Docker Desktop의 Linux VM에서 돌기 때문에 Mac GPU(Metal)를
  쓸 수 없고, CPU 추론 시간은 실제 운영 환경을 대표하지 않는다. Jenkins는 HTTP로 이미 떠 있는 ocrserver를 호출만 한다.
- `benchmark.py`는 라벨 파일·서버 URL·반복 횟수를 인자로 받고, 같은 입력이면 같은 순서로 요청한다.

### 5.1 Jenkins

- ErpMSA 파이프라인과 분리된 Jenkins 작업 `ocr-benchmark`(수동 실행 + 선택적 야간 실행)로 둔다.
  ErpMSA CI가 OCR 서버 상태에 따라 실패하지 않게 하기 위함이다.
- 단계: 서버 `/health/ready` 확인 → `benchmark.py` 실행 → `summary.json`·`per-file.csv` 보관 → `junit.xml` 게시.
- `junit.xml`의 테스트 케이스는 임계값 검사다. 예:
  자동승인 오답 0건, 후보 재현율 ≥ 기준, p95 ≤ 기준. Jenkins의 테스트 추이 그래프로 빌드별 통과 여부를 본다.
- 숫자 추이 그래프가 필요하면 Plot 플러그인을 `jenkins/Dockerfile`에 추가해야 한다(현재 미설치).

### 5.2 Grafana

벤치마크 결과는 Pushgateway를 거쳐 Grafana에서 본다 (2026-11-02 적용).

- ErpMSA `compose.yaml`의 `pushgateway`(`127.0.0.1:9091`, 볼륨 `erpmsa-pushgateway-data`)가 결과를 받는다.
- Prometheus `pushgateway` 작업(`honor_labels: true`)이 `job="ocr_benchmark"`, `run="<--name>"` 라벨을 유지해 수집한다.
- 대시보드 `ErpMSA/ErpMSA OCR Benchmark`(uid `erpmsa-ocr-benchmark`): 실행 목록, 웜·콜드 지연, 사업자번호 지표,
  필드 일치율·CER, 결과 분류, 합격 검사. 상단 `실행` 변수로 Before/After를 골라 비교한다.
- 같은 `--name`으로 다시 push하면 그 실행의 값이 교체된다. 실행 이름은 `before-local-q8`, `after-modal-l4`처럼 구분한다.
- Grafana 대시보드 파일은 `/etc/grafana/dashboards`로 옮겼다. 기존 위치(`/var/lib/grafana/dashboards`)는
  `grafana-data` 볼륨에 가려져, 볼륨 생성 이후 추가한 대시보드가 로컬에 나타나지 않았다.

아래는 운영 중 실시간 지표를 볼 때의 추가 작업이다(미적용).

Grafana에 운영 OCR 패널을 넣으려면 아래 두 가지가 모두 필요하다.

1. ocrserver에 `/metrics` 노출(prometheus-client):
   - `ocr_request_duration_seconds{stage, status}` 히스토그램 (stage = load / pass1 / pass2 / total)
   - `ocr_requests_total{status}` 카운터 (AUTO_ACCEPTED / REVIEW_REQUIRED / NOT_FOUND / ERROR)
2. Prometheus가 ocrserver를 수집하도록 `monitoring/prometheus/prometheus.yml`에 대상 추가
   (예: `host.docker.internal:8000`).

이렇게 하면 **운영 중 속도와 상태 분포**는 보이지만, 정답이 없으므로 **정확도는 Grafana에서 볼 수 없다**.
정확도는 Jenkins 벤치마크 결과로만 본다. 2번은 설계도(`architecture/services.json`)에 없는 수집 대상을 ErpMSA
모니터링 구성에 추가하는 일이므로 별도 승인 후 진행한다.

## 6. 합격 기준 (초안, 첫 측정 후 확정)

| 지표 | 초안 |
|---|---|
| 자동승인 정밀도 | 100% (자동승인 오답 0건) |
| 후보 재현율 | 첫 측정값을 기준선으로 기록 후 결정 |
| 처리 실패율 | 0% |
| 종단 p95 (동시성 1, 워밍업 후) | 첫 측정값을 기준선으로 기록 후 결정 |

기준선이 없는 상태에서 숫자를 정하지 않는다. 첫 실행 결과를 기준선으로 남기고, 이후 변경(임계값·전처리·모델)은
같은 데이터셋·같은 환경에서 기준선과 비교한다.

## 7. 구현 순서

1. (완료) 데이터셋 구조·라벨 도구 `eval/labels.py`, gitignore. 확정 라벨 1건.
2. ocrserver: 단계별 시간을 `Server-Timing` 헤더로 응답에 포함. 벤치마크는 헤더가 있으면 자동으로 읽는다.
   (로그의 0.001초 응답은 `tests/test_ocr_api.py`의 `FakeOcrService`가 남긴 것이다. 벤치마크는 측정 후
   `/health/ready`의 `backend`를 검사한다.)
3. (완료) `eval/benchmark.py`와 라벨·합성·벤치마크 테스트. 이번 검증은 평가 도구 테스트 23건 통과.
4. (완료) 동일 41건으로 로컬 Before 및 Modal After 기준선 측정.
5. (미구현) Jenkins `ocr-benchmark` 작업 추가.
6. (완료) Pushgateway·Prometheus를 통한 오프라인 결과와 Grafana OCR 대시보드. 운영 `/metrics`는 미구현.

## 8. 전후 비교: 로컬 OCR 서버(Before) → Modal 서버리스(After)

KostaErpServer(`2026_05_KOSTA/KostaErpServer`)는 `PythonOcrClient`가 `external-api.python-ocr-url`로 OCR 서버를
호출한다. 이 URL을 로컬 ocrserver에서 Modal 앱 `eum-ocr`로 바꾼 것이 전후 변경이다.

### 8.1 두 환경의 차이

| 항목 | Before: 로컬 | After: Modal |
|---|---|---|
| 실행 | Mac, 이번 측정은 `fastapi run`, llama.cpp | 이번 측정은 테스트 앱 `eum-ocr-bench`, llama.cpp CUDA 이미지 |
| 가속기 | Apple GPU(Metal, `LLAMA_CPP_NGL=99`) | NVIDIA L4 |
| 모델 | `surya-2-Q8_0.gguf`(8비트 양자화, 674MB) | `surya-2.gguf`(원본) |
| 상시 컨테이너 | 측정용 서버 시작 후 첫 요청을 콜드로 측정 | `min_containers=0`, scaledown 설정 300초; 실제 종료는 로그 확인 필요 |

- 하드웨어와 모델 파일이 **동시에** 바뀌었다. 속도 차이를 GPU 덕분으로, 정확도 차이를 모델 덕분으로 단정할 수 없다.
  원인을 나누려면 로컬에서 원본 `surya-2.gguf`로도 한 번 더 측정한다(Before-B).
- Modal은 컨테이너 0개에서 시작하므로 **콜드 스타트**(컨테이너 기동 + 모델 로드)가 전후 비교의 핵심 항목이다.
  웜 상태 지연과 반드시 나눠 보고한다.

### 8.2 기존 기록의 한계

- Before: 1.1의 로컬 로그 53건뿐이다. 2026-06-13 15:26 전후로 모델 파일이 바뀌었을 수 있어 조건이 섞여 있다.
- 재측정 전 After: 2026-07-01 ~ 2026-10-11 구간 `modal app logs eum-ocr` 조회 결과가 0건이었다(로그 보존 기간 경과로 추정).
  당시 측정 파일도 찾지 못했다. 이번 테스트 앱 결과는 8.5절의 별도 파일로 남겼다.
- KostaErpServer에는 OCR 호출 시간 측정 코드(Micrometer Timer 등)가 없다.

따라서 기존 로그를 Before로, 기억이나 다른 기록을 After로 맞대지 않는다. 같은 데이터셋·같은 `benchmark.py`로
두 환경을 다시 측정해 비교한다.

### 8.3 비교 실험

| 실행 | 대상 URL | 측정 |
|---|---|---|
| Before-A | 로컬, Q8_0 | 웜 지연, 정확도 |
| Before-B | 로컬, 원본 `surya-2.gguf` | 웜 지연, 정확도 (모델 영향 분리용) |
| After-cold | Modal, 새 컨테이너 상태 | 마지막 요청 후 최소 600초 대기하고 컨테이너 ID·기동 로그 검증. 이번 1회, 확장 실험은 최소 5회 |
| After-warm | Modal, 웜 상태 | 웜 지연, 정확도 |

- 측정 위치는 KostaErpServer가 실제로 호출하는 위치와 같게 한다(로컬 Mac에서 호출하면 네트워크 왕복이 After에만 더해진다는 점을 결과에 명시).
- 보고: 환경별 p50/p95/최대, 콜드 스타트 분포, 정확도 지표(3장)를 한 표에 나란히 둔다.
- Modal 비용(L4 시간당 단가 × 실행 시간)과 1건당 비용도 After에 함께 적는다.
- 같은 이미지라도 두 환경에서 결과가 다른 문서는 목록으로 남겨 오류 원인을 확인한다.

이번 작업은 Before-A와 After의 OCR 단독 비교다. Before-B, 반복 콜드 분포, 실제 가입 종단 호출 및 과금은 측정하지 않았다.

### 8.4 Modal 측정용 테스트 환경

- 기존 After 측정은 브라우저(회원가입 화면 → KostaErpServer → Modal)에서 한 것이다. 이 값에는 브라우저 업로드,
  Spring 처리, 사업자 검증 API 호출이 함께 들어 있어 OCR 시간만 따로 볼 수 없다.
- Modal `@modal.asgi_app()`은 공개 HTTPS 주소를 가지므로 배포 서버를 거치지 않고 `benchmark.py`에서 바로 호출할 수 있다.
- 운영 앱 `eum-ocr`을 벤치마크에 쓰지 않는다. 콜드 스타트 측정을 위해 컨테이너를 내리고 올리는 동안 실제 가입 요청이
  영향을 받는다. 대신 같은 코드로 **별도 앱**을 배포한다. `modal_app.py`가 이미 `MODAL_APP_NAME`을 환경변수로 받는다.

```bash
MODAL_APP_NAME=eum-ocr-bench MODAL_MIN_CONTAINERS=0 uv run modal deploy modal_app.py
```

- 측정이 끝나면 `modal app stop eum-ocr-bench`로 내린다. L4 GPU 사용 시간만큼 비용이 발생한다.
- 계층별로 나눠 잰다.

| 구간 | 방법 |
|---|---|
| OCR만 | `benchmark.py` → `eum-ocr-bench` (Before는 로컬 ocrserver) |
| 종단(가입 요청 전체) | KostaErpServer를 로컬에서 띄우고 `OCR_API_URL`만 바꿔 같은 가입 API 호출 |

### 8.5 이번 실행 조건과 원본 결과

시간은 모두 KST다. 두 실행은 같은 Mac의 `Darwin arm64 Python 3.14.0` 클라이언트에서 차례로 요청했다.
Before 호스트는 Apple M4 Pro, `Mac16,8`, 메모리 48GiB다. 로컬 Q8_0 파일은 674,270,944바이트다.
After는 인계된 `eum-ocr-bench` 배포를 그대로 사용했으며 운영 앱 `eum-ocr`에는 요청·배포·중지를 하지 않았다.
두 환경의 llama-server 로그에서 `--parallel 1 --ctx-size 16384 -ngl 99`와 같은 mmproj 스냅샷
`6a3a4c30e5e74446d4f8b6afd05b2f2da970f470` 경로를 확인했다. 추론 서버 바이너리 버전과 배포된 전체 소스의 원격 해시는 별도로 수집하지 않았다.

| 조건 | Before | After |
|---|---|---|
| 실행 이름 | `before-local-q8` | `after-modal-l4` |
| 시작 ~ 종료 | 15:55:29 ~ 16:04:49 | 16:07:32 ~ 16:13:26 |
| 대상 | `http://127.0.0.1:8000` | Modal 벤치마크 앱의 HTTPS 주소 |
| 입력·순서 | `s001`, `syn-11-000`~`039`, 동일 이미지 바이트 | 동일 |
| 요청 수 | 콜드 1 + 워밍업 3 + 웜 41 = 45 POST | 동일 |
| 반복·동시성 | 문서당 1회·동시성 1 | 동일 |
| 클라이언트 타임아웃 | 인계 명령대로 600초 | 인계 명령대로 900초 |
| 모델 | `surya-2-Q8_0.gguf`, Metal | `surya-2.gguf`, CUDA/L4 |

타임아웃 상한은 다르지만 두 실행 모두 600초 이내에 성공해 타임아웃으로 제외된 요청은 없다.
클라이언트가 한국의 Mac이므로 Modal 지연에는 HTTPS 업로드·왕복 지연이 포함된다. Spring·브라우저 가입 처리 시간은 포함하지 않는다.
콜드와 워밍업은 정확도·웜 지연 집계에서 제외했다. 반복이 1회라 실행 간 변동성·반복 일관성은 평가하지 못했다.

원본 결과는 다음 디렉터리의 `summary.json`, `per-file.csv`, `junit.xml`이다. 인식 원문은 이 문서에 옮기지 않았다.

- Before: `~/Desktop/ocrserver/ocrserver/eval/results/20261102-155529-before-local-q8/`
- After: `~/Desktop/ocrserver/ocrserver/eval/results/20261102-160732-after-modal-l4/`

측정 전후 다음 로컬 소스 해시가 동일했다. 기존 미커밋 구현은 수정하지 않았다.

| 파일 (`ocrserver/ocrserver` 기준) | SHA-256 |
|---|---|
| `eval/benchmark.py` | `a7518d0d51ef1aedbd23bd14416c776ff73a64d5e0dfb75f822166a3ca336d28` |
| `eval/synth.py` | `bec72e6a05d8f987c32f2a01aee764462c80bbb2a02d0f8ea628bbd3a11f31c0` |
| `app/business_registration_number.py` | `03bd56fde3d325dd84c57f51dcfdf4b313371b761ea6572287f621fbb5f0718c` |
| `app/services/surya_ocr_service.py` | `4476df6a628b840d2331e3e449cd6a2d7827581d35f0ffe4cdeed464e02e8b66` |
| `main.py` | `f7c4a36f2d0f3a1b7ee3b4819add155554ba58fe74d817adb88b6372c9fca978` |
| `modal_app.py` | `28f79b538109acbf0f7bbb2e0d6fd9f62d321c680278ab539f24d96eabcd0d01` |

환경 유지 지시를 벗어난 사항이 있다. 측정 전 `uv run modal app logs --help` 실행 시 uv가 `.venv`를 자동 재생성했다.
이는 인계 문서의 `.venv` 유지 지시를 놓친 의도하지 않은 변경이며, 원래 환경을 복원했다고 보지 않는다.
이후 Modal CLI는 `uv run --no-sync`를 사용했고, 두 측정은 재생성 후의 동일한 Python 환경에서 실행했다.
`uv.lock`은 작업 시작 때와 같은 SHA-256 `81ef2ddce88f85b84c10299bd4103e26684d796f6661daa7ac91e7cad4f86c4a`였다.

### 8.6 상세 결과와 실제·합성 분리

| 전체 지표 | Before | After |
|---|---|---|
| 웜 p90 / 평균 | 9.13s / 12.64s | 4.86s / 4.23s |
| 직렬 처리의 환산 문서 수/분 (`60 / 웜 평균`) | 4.75 | 14.18 |
| A 자동승인·정답 / B 자동승인·오답 | 7 / 0 | 7 / 0 |
| C 후보 적중 / D 후보 누락 | 33 / 1 | 33 / 1 |
| E 미검출 / F 실패 | 0 / 0 | 0 / 0 |
| 상호 CER / 대표자 CER | 0.1028 / 0.2439 | 0.1028 / 0.0732 |
| 유효기간 시작·종료 일치 (각각, 빈 값 일치 포함) | 97.56% (40/41) | 97.56% (40/41) |
| 유효기간 시작·종료 일치 (각각, 값이 있는 확인서만) | 90.91% (10/11) | 90.91% (10/11) |
| 유효기간 시작·종료 CER (각각, 값이 있는 11건) | 0.0909 | 0.0909 |

환산 문서 수/분은 병렬 부하 시험의 처리량이 아니다. p95는 41개 표본의 선형 보간 값이며,
약 130초인 두 건이 41건 중 두 건에 그쳐 Before의 p95는 10.10초다. 긴 응답이 가려지지 않도록 최대와 평균도 함께 기록했다.

| 출처별 지표 | 실제 Before (n=1) | 실제 After (n=1) | 합성 Before (n=40) **실제보다 높게 나올 수 있음** | 합성 After (n=40) **실제보다 높게 나올 수 있음** |
|---|---|---|---|---|
| 자동승인 정밀도 | 산출 불가 (0/0) | 산출 불가 (0/0) | 100% (7/7) | 100% (7/7) |
| 자동승인율 | 0% (0/1) | 0% (0/1) | 17.5% (7/40) | 17.5% (7/40) |
| 후보 재현율 | 0% (0/1) | 0% (0/1) | 100% (40/40) | 100% (40/40) |
| 상호 일치 / CER | 0/1 / 0.8000 | 0/1 / 0.8000 | 35/40 / 0.0854 | 35/40 / 0.0854 |
| 대표자 일치 / CER | 1/1 / 0 | 1/1 / 0 | 36/40 / 0.2500 | 37/40 / 0.0750 |
| 유효기간 시작·종료 일치 (각각, 값이 있는 확인서만) | 1/1 | 1/1 | 9/10 | 9/10 |
| 처리 실패 | 0/1 | 0/1 | 0/40 | 0/40 |

날짜 전체 일치 40/41에는 날짜가 없는 사업자등록증 30건의 null 일치가 포함된다.
합성만의 집계도 39/40이지만, 날짜가 있는 합성 확인서에서는 9/10이다.
상호·대표자 누락은 두 환경 모두 각각 3건, 날짜 시작·종료 누락은 각각 1건이며 null 정답의 오검출은 0건이었다.
실제 1건은 두 환경 모두 D 분류로, 합성 40/40의 후보 재현율을 실제 손글씨 서류에 일반화할 수 없다.

사업자등록증 30건은 두 환경 모두 자동승인 0/30·후보 정답 30/30이며, 확인서 11건은 자동승인 7/11·후보 정답 10/11이었다.
분류와 필드 일치 여부가 달라진 문서는 `syn-11-020`(사업자등록증, photo)의 대표자뿐으로, Before 불일치→After 일치였다.
하드웨어와 모델을 분리하지 않았으므로 이 개선을 비양자화의 효과로 단정하지 않는다.

| 지연 이상치 | Before HTTP / 2차 재인식 로그 | After HTTP / 2차 재인식 로그 |
|---|---|---|
| `syn-11-003` (확인서, 체크섬 오류, lowres) | 130.0458s / 126.497s | 4.0006s / 1.259s |
| `syn-11-023` (확인서, 체크섬 오류, scan) | 129.4575s / 123.872s | 3.8851s / 0.403s |

두 건은 두 환경 모두 HTTP 200·C 분류였다. 이번 Modal 웜 요청 중 30초 초과는 없었다.
표의 2차 시간은 동시성 1에서 순서와 요청 ID를 대조한 진단용 로그 값이며 응답의 단계별 지표가 아니다.
두 환경 모두 `Server-Timing`이 없어 `serverStages`가 비어 있으므로 단계별 p50/p95와 2차 재인식의 전체 실행 비율은 미측정이다.

### 8.7 Modal 콜드 검증과 Grafana 확인

직전 Modal 요청은 15:41:15(`GET /health/ready`, 503), 이번 시작은 16:07:32였다.
간격은 1,577초(26분 17초)로 최소 10분을 충족했다. 측정 전 로그 조회는 OCR 엔드포인트를 호출하지 않았다.

| 콜드 근거 | 확인 내용 (KST) |
|---|---|
| 이전 컨테이너 | `ta-01M6DEVVFCA9SBZ91R90KZGXTR` |
| 이번 컨테이너 | `ta-01M6DHFJP4NTG3PJAG1WWF76KR`, 이전과 다른 ID |
| L4 배정 대기 로그 | 16:09:03 및 16:09:48, `waiting to be scheduled on a GPU_L4 worker` |
| 새 컨테이너 첫 POST | 16:09:54.590, 요청 ID `2267a97e` |
| 모델 기동 완료 | 같은 컨테이너 16:10:03.632, `llamacpp server ready` |
| 첫 POST 성공 | 16:10:11.125, 서버 미들웨어 16.535초, HTTP 200 |
| 클라이언트 콜드 | 158.7131초, 실패 0/1 |

클라이언트 158.71초와 서버 16.54초의 차이 약 142.18초에는 GPU 대기·컨테이너 기동·네트워크 등이 섞인다.
순수 GPU 대기 시간이나 순수 모델 로딩 시간으로 단정하지 않는다. 콜드 1회만으로 일반적인 분포를 제시할 수 없다.
최종 로그에서 45 POST 모두 같은 새 컨테이너였으며 다른 컨테이너의 웜 요청이 섞이지 않았음을 확인했다.

Grafana `http://127.0.0.1:3000/d/erpmsa-ocr-benchmark`의 11개 패널에서 두 실행의 PromQL 결과가 존재하고,
문서 수·p50/p95/최대·사업자번호 지표가 `summary.json`과 일치했다. 실제 화면에서도 요약, 지연, 정확도, CER, 분류,
실제/합성 분리, 실행 목록, 합격 검사의 두 실행을 확인했다. Before는 파랑, After는 주황이다.

이후 사용자 요청으로 실제/합성 비교 패널에서 실제 자동승인율·실제 후보 재현율·실제 상호 일치 3개 항목은 표시에서 제외했다.
실제 대표자 일치와 합성 지표 4개는 유지했다. 이 표시 변경은 원본 측정값과 이 문서의 결과 표를 변경하지 않는다.

화면 확인 중 5개 막대그래프는 데이터가 있어도 그려지지 않았다. `legend.placement="top"`을
지원되는 `bottom`으로 바꾸고 Grafana만 `docker compose up -d --build --no-deps grafana`로 반영해 렌더링을 확인했다.
배치 근거는 [Grafana 공식 막대그래프 범례 설정](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/bar-chart/#legend-options)의 Bottom/Right다.
실행 목록과 합격 검사 표는 전체 폭으로 넓혀 Before·After 열을 함께 볼 수 있게 했다. PromQL과 측정값은 변경하지 않았다.

검증 자료는 로컬 `/private/tmp/erpmsa-ocr-benchmark-20261102/`에 저장했다.
`dataset-snapshot.json`, `comparison-evidence.json`, `modal-cold-evidence.json`, `grafana-prometheus-verification.json`을 참조할 수 있다.
서버 로그에는 개인정보가 있으므로 Git이나 이 문서에 첨부하지 않는다. `/private/tmp`는 임시 영역으로 장기 보관 위치가 아니다.

### 8.8 알려진 문제·검증 범위·종료 처리

1. **사업자등록증 자동승인 0건**: `STRONG_KEYWORDS`에 `등록번호`가 없다.
   현재 코드와 30/30건의 C 분류를 확인했다. 키워드 가점 누락이 원인으로 보이지만 수정 검증은 하지 않았다.
2. **필드 누락**: 띄어 쓴 `상   호`·`성   명`에서 누락하는 알려진 문제는 남아 있다.
   이번 필드 누락은 각각 3건이다. 개별 누락의 원인을 모두 확정한 것은 아니다.
3. **최초 측정의 Modal 준비 상태 503**: 당시 `modal_app.py`는 `inference_health_url`에 `/health`를 붙이지 않고 기본 URL을 설정했다.
   16:13:26 준비 상태 요청도 503이었고, After의 `backend_is_expected`는 FAIL, 기록상 backend는 `null`/Grafana에서는 `unknown`이다.
   당시 llama.cpp 기동 로그는 있었지만 준비 상태 API는 실패했다. 벤치마크 종료 코드 1을 성공으로 바꾸지 않았다. 후속 수정은 8.9절을 참조한다.
4. **2차 재인식 장시간화**: 이번에는 로컬 2건에서 약 124~126초를 확인했다. Modal에서는 재현되지 않았지만 기존 문제의 해소로 보지 않는다.
5. **종료 후 자식 프로세스 잔류**: 로컬 FastAPI 종료 후 llama-server가 남아 이번에 시작한 PID만 종료하고 잔류 없음을 확인했다.
6. **Modal 303과 Spring**: 평가 클라이언트의 `follow_redirects=True`를 유지했다. 이번 리다이렉트 이력은 저장하지 않았다.
   KostaErpServer `PythonOcrClient`의 303 처리와 실제 가입 흐름은 미검증이며 해당 프로젝트는 변경하지 않았다.

평가 도구의 `tests.test_eval_labels`·`tests.test_eval_benchmark`·`tests.test_eval_synth` 총 23개 테스트가 PASS였다.
ErpMSA 구조 검사는 기본·`--ci`·`--performance` 3종 PASS였다. Before JUnit은 3/3 PASS, After는 2/3 PASS(준비 상태 1건 FAIL)였다.
측정 후 `uv run --no-sync modal app stop eum-ocr-bench --yes`로 테스트 앱을 중지했다.
앱 목록에서 `stopped`, 실행 작업 0개, 중지 시각 16:15:49를 확인했다.
로컬 OCR 서버도 종료했으며 모니터링 3개 서비스와 기존 볼륨은 유지했다. 커밋·푸시는 하지 않았다.

### 8.9 준비 상태 점검 후속 수정 (2026-11-02)

`ocrserver/modal_app.py`가 `backend_handle.base_url`에서 `/v1`을 제거한 뒤 `/health`를 붙이도록 수정했다.
기존 코드는 `/v1`만 제거해 루트 경로를 호출했다. `main.py`의 준비 상태 처리나 OCR 추출기는 바꾸지 않았다.

회귀 테스트 `tests/test_modal_health.py`를 추가해 잘못된 경로에서 503이 재현됨을 먼저 확인했다.
테스트는 Surya 0.20.0의 실제 `ServerHandle` 타입을 사용한다. 정상 백엔드는 준비 상태 200과 `backend=llamacpp`를 반환하고,
백엔드가 503을 반환하거나 연결할 수 없을 때는 준비 상태도 계속 503을 반환한다.
전체 로컬 테스트 39건이 통과했고, 실제 로컬 llama-server와 동일한 Modal 초기화 코드를 연결해
`/health/ready`의 200 및 `{"status":"UP","backend":"llamacpp"}` 응답도 확인했다.

수정본은 운영 앱이 아닌 `eum-ocr-bench`에 배포했다. 실제 Modal에서 다음을 확인했다.

- 18:38:26 벤치마크 종료 시 `/health/ready` HTTP 200, `backend=llamacpp`.
- 18:39:52 별도 직접 호출에서도 HTTP 200, `{"status":"UP","backend":"llamacpp"}`.
- 새 실행 `after-modal-l4-healthfix`의 `backend_is_expected`, `auto_accept_wrong_is_zero`, `failure_rate_is_zero` 모두 PASS, 종료 코드 0.

| 항목 | 최초 After `after-modal-l4` | 수정 후 After `after-modal-l4-healthfix` |
|---|---|---|
| 측정 시각 (KST) | 16:07:32 ~ 16:13:26 | 18:33:42 ~ 18:38:26 |
| 웜 p50 / p95 / 최대 (각 n=41) | 4.28s / 5.40s / 6.88s | 4.49s / 5.71s / 7.84s |
| 콜드 (각 n=1) | 158.71s | 77.08s |
| 자동승인 정밀도 / 자동승인율 | 7/7 / 7/41 | 7/7 / 7/41 |
| 후보 재현율 | 40/41 | 40/41 |
| 상호 / 대표자 일치 | 35/41 / 38/41 | 35/41 / 38/41 |
| 웜 처리 실패 / 해당 실행의 콜드 실패 | 0/41 / 0/1 | 0/41 / 0/1 |
| 준비 상태 검사 | FAIL (`backend=null`, 503) | PASS (`backend=llamacpp`, 200) |

합성 서류 비중과 실제 1건의 한계는 이전과 같다. 정확도 집계는 최초 After와 같았다.
두 After의 지연 차이는 별도 시각의 재실행 값으로, 준비 상태 주소 수정에 따른 속도 개선·저하로 해석하지 않는다.

후속 작업의 첫 시도는 L4 배정 대기 로그가 남은 상태에서 콜드 요청이 541.59초 후 HTTP 500으로 실패해 중단했다.
위 수정 후 표는 그 실패를 지운 값이 아니라, 이후 별도 재시도에 성공한 실행의 값이다.
앞선 테스트 앱 중지 18:23:31부터 새 실행 시작 18:33:42까지 611초를 확보했다.
새 컨테이너 `ta-01M6DSRPZ3X02YCY01R5K5Z04R`의 첫 POST는 18:34:42.891,
`llamacpp server ready`는 18:34:50.754였으며 45 POST가 모두 이 컨테이너에서 처리됐다.

원본 결과는 `~/Desktop/ocrserver/ocrserver/eval/results/20261102-183342-after-modal-l4-healthfix/`에 저장했다.
최종 `modal_app.py` SHA-256은 `7c85301d09d4417f41d7598f98ac030a5e8441eb167b25a6ae278523235c249a`다.
기존 Before·After 결과 파일은 그대로 유지했다. 추출기·API·설정·`uv.lock`을 바꾸지 않았고 `.venv` 동기화도 하지 않았다.

Grafana 기본 비교 대상을 `before-local-q8`와 `after-modal-l4-healthfix`로 바꿨다.
기존 `after-modal-l4`의 FAIL은 원본 보고서와 지표에 남아 있으며 성공으로 덮어쓰지 않았다.
현재 비교쌍의 11개 패널을 Prometheus에서 확인했고 합격 검사 6개 값(Before 3개·After 3개)이 모두 1이다.
실제 지표 3개를 숨긴 사용자의 표시 설정도 유지했다.

검증 자료는 `/private/tmp/erpmsa-ocr-healthfix-20261102/`의 `unit-tests.log`, `local-real-backend.log`,
`verified-result.json`, `remote-ready.json`, `remote-evidence.json`, `grafana-prometheus-verification.json`에 있다.
실패한 첫 시도의 `benchmark-attempt1.log`도 따로 보관했다. 검증 후 테스트 앱을 중지했고 운영 앱 `eum-ocr`은 변경하지 않았다.
커밋·푸시는 하지 않았다.

## 9. 확인이 필요한 사항

- 실제 서류를 종류별로 추가해 운영 문서 정확도를 다시 평가해야 한다. 이번에는 사업자번호·상호·대표자·유효기간 모두 평가했다.
- 추출기 키워드·2차 재인식·프로세스 정리 결함 수정은 별도 작업이다. 준비 상태 URL 후속 수정은 8.9절에 기록했다.
- Spring의 Modal 303 응답 처리, 반복 콜드 분포, 단계별 응답 계측 및 실제 과금은 미확인이다.
