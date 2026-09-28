# G2 실제 3서비스 검증 기록

> Codex 설계·구현 / Herdr의 같은 작업 폴더 Claude 독립 검토.
> 기준: `feat/status`, HEAD `d11461b52a0e2cb90521b3217d55f960d4c0676e` + 검증 도구·제품 수정 미커밋 변경.
> 제품 수정 후 진행: **G2-DEF-01 구현 완료, G1 119개 PASS, G2 10/10 PASS**. 아래의 9 PASS/1 FAIL은 수정 전 기록이며 삭제하지 않는다.

## 범위와 실행 설계

[정상 흐름 설계](normal-flow-verification-design.md)의 G2 항목인 NF-02, NF-04~12를 실제 FoodMaterials·Menus·Disposals JAR와 HTTP로 검증한다. G1의 성공 manifest와 현재 애플리케이션·빌드·테스트 입력 해시가 일치하는지 먼저 검사한다. 3개 bootJar를 다시 빌드하고 이번 실행의 임시 폴더에 복사한 뒤 SHA-256을 기록한다.

단일 임시 MariaDB의 4개 schema(`itemdb`, `inventorydb`, `menusdb`, `disposalsdb`)를 사용한다. FoodMaterials가 소유하는 두 schema와 메뉴·폐기 저장소를 분리하되, 이 시험으로 서로 다른 DB 서버 장애 격리를 검증하지는 않는다. MariaDB는 run label·컨테이너 ID·시작 전 목록·tmpfs·영구 mount 부재·loopback 임시 포트를 검사한 후 초기화한다. 애플리케이션은 기본 포트 대신 이번 실행의 loopback 임시 포트에서만 기동하며, 각 HTTP 요청 전에 `lsof`로 해당 listener를 연 PID가 이번 JVM인지 확인한다.

임시 RSA 키로 합성 계정 A=101/B=202 토큰을 만든다. 정상 kid/issuer/audience 대조군 후 인증 조건을 하나씩 변형한다. 개인키는 JVM의 작업·tmp 디렉터리와 분리한 검증기 credential 폴더에 보관하며 서비스에는 복사한 공개키 디렉터리만 설정한다. DB env 파일은 컨테이너 생성 직후 지운다. 같은 OS 사용자로 실행하므로 이 디렉터리 분리는 OS 권한에 의한 비밀 접근 격리를 보장하지는 않는다. JVM은 제한된 환경으로 실행하고 discovery는 끈다. 이 결과는 Account 발급 토큰·Gateway·Eureka·Outbox·관측이나 G3/G4의 증거가 아니다.

업무 데이터는 API로 만들며 SQL은 SELECT 권한만 가진 별도 verifier 계정과 `START TRANSACTION READ ONLY`로 조회한다. 원장 합계·수량 연속성·폐기 명령 ID·소유 계정·version을 API와 대조한다. NF-09~11 동시성 사례는 시작 장벽을 사용하고 각 3회 새 fixture로 반복한다. 요청별 시작·종료 시각을 나노초 단위 Unix 시각으로 기록해 겹치는 구간을 대조할 수 있게 한다.

인증 실패 시 후속 업무 쓰기를 중단한다. 다른 assertion 실패는 전체 FAIL을 유지하면서, 실패 fixture에 의존하지 않는 사례를 진단 목적으로 계속한다. 선행 fixture가 필요한 사례는 NOT_RUN으로 남긴다. 예상 밖 PENDING/202를 재시도로 성공 처리하거나 DB를 수동 보정하지 않는다.

## 재현 명령과 산출물

```sh
python3 -m unittest scripts/test_g2_verification.py
python3 scripts/run-g2-verification.py --offline
```

- [실행기](../scripts/run-g2-verification.py): G1 증거 확인, 빌드·기동·키·DB 소유권·증거 수집·정리.
- [시나리오](../scripts/g2_scenarios.py): HTTP 기대값, 원장 불변식, 계정 경계, 동시성 및 DB 읽기 대조.
- `.verification/<runId>/manifest.json`: 소스/JAR hash, 단계 상태, G0·G1 연결, migration 이력, 프로세스·컨테이너 정리.
- `http.jsonl`: 시나리오별 요청 method/path/body와 실제 상태·응답. Authorization·JWT·Cookie·비밀번호·개인키 제외.
- `NF-xx-database.json`: 해당 사례 종료 시 5개 업무 테이블의 합성 데이터.
- 각 서비스 빌드/실행 로그와 DB 로그: 임시 폴더를 제거하기 전에 비밀값을 가려 보존.

## 발견 및 수정한 제품 결함

### G2-DEF-01 — 잘못된 식자재 페이지 값이 400 대신 500

첫 실행 [6a057254a96f manifest](../.verification/6a057254a96f/manifest.json)에서 정상 신뢰 토큰으로 `GET /foodmaterials?page=-1`을 요청했을 때 기대 400 대신 `500 / INTERNAL_SERVER_ERROR`가 반환됐다. 후속 실행은 `/foodmaterials?size=101`도 같은 500으로 확인했다. [FoodMaterials 로그](../.verification/812c7a9fcc67/FoodMaterialsService.log)에 `jakarta.validation.ConstraintViolationException: list.page` / `list.size`와 `MethodValidationInterceptor`가 기록돼 있다.

확인한 코드: [FoodMaterialController](../FoodMaterialsService/src/main/java/com/oopsw/foodmaterialsservice/web/FoodMaterialController.java)의 클래스 `@Validated`와 page `@Min(0)`. [ApiExceptionHandler](../FoodMaterialsService/src/main/java/com/oopsw/foodmaterialsservice/advice/ApiExceptionHandler.java)의 수정 전 코드는 `HandlerMethodValidationException`을 400으로 처리하지만 `ConstraintViolationException` 전용 처리가 없어 일반 `Exception`의 500 경로로 들어갔다.

수정 전에 비교한 두 대안은 다음과 같다.

1. AOP의 `ConstraintViolationException`을 `INVALID_REQUEST / 400`으로 명시 매핑하고 회귀 테스트 추가.
2. 컨트롤러의 클래스 `@Validated`를 제거해 Spring MVC 메서드 검증으로 통일하되, 해당 컨트롤러의 모든 입력 제약과 기존 오류 계약을 회귀 검증.

수정 전 G2 결함 재현은 위 두 목록 요청이었다. 이후 사용자의 구현 요청에 따라 제품 예외 처리기를 변경했고, 같은 컨트롤러의 양수 ID 제약도 GET/PUT/DELETE의 ID 0/-1로 회귀 검증했다.

**구현한 G2-FIX-01**은 기존 AOP 방식을 유지하는 1번이다. 변경 파일은 예외 처리기와 [예외 처리 단위 테스트](../FoodMaterialsService/src/test/java/com/oopsw/foodmaterialsservice/advice/ApiExceptionHandlerTest.java), [서비스 통합 테스트](../FoodMaterialsService/src/test/java/com/oopsw/foodmaterialsservice/FoodMaterialsServiceIntegrationTest.java)다. 기존 테스트가 다루지 않았던 페이지 범위 오류·품목 ID 오류 회귀를 추가했다.

`ConstraintViolationException` 전용 처리기는 HTTP 400·`INVALID_REQUEST`를 반환하며, 오류 경로의 마지막 이름(page/size/foodMaterialId)을 `fieldErrors`에 넣고 중복 제거 후 정렬한다. 클래스 `@Validated`를 유지해 기존 잘못된 body의 필드 오류 계약을 보존했다. 추가한 단위 테스트 2개·통합 테스트 4개는 페이지(-1/0/101), ID(0/-1)의 GET/PUT/DELETE, 정상 페이지 경계, PUT body 오류와 DB 불변, 일반 서버 오류의 500 유지를 확인한다.

제품 수정에 대한 [Claude 독립 검토 원본](../.verification/33f3464bbf52/claude-fix-review.md)은 **승인·차단 결함 없음**이다. 카탈로그 인자 오류의 fieldErrors가 채워지고 다른 서비스의 기존 인자 오류는 빈 배열을 유지한다는 응답 차이를 문서화했다. 향후 서비스 계층·엔티티에 Bean Validation을 추가하면 이 전역 매핑 범위를 다시 검토해야 한다는 의견도 남긴다. 현재는 해당 경로의 기존 계약을 유지한다.

## 제품 수정 후 재검증

2026-09-28 같은 작업 트리에서 G1을 먼저 통과한 뒤 새 JAR로 G2를 실행했다. 두 manifest의 전체 소스 해시를 현재 파일과 대조해 모두 일치했다.

| 단계 | 실행 ID·시간(KST) | 결과 |
|---|---|---|
| G1 | [33f3464bbf52](../.verification/33f3464bbf52/manifest.json), 16:39:10~16:40:53 | 9개 프로젝트 119개 테스트 PASS, 실패·오류·SKIP 0. FoodMaterials 38→44개 |
| G2 | [54712d144fdf](../.verification/54712d144fdf/manifest.json), 16:41:10~16:42:25 | NF-02·04~12 10개 모두 PASS, 입력 실패 0 |

[수정 후 HTTP 기록](../.verification/54712d144fdf/http.jsonl)에서 NF-08의 잘못된 입력 16건이 모두 `400 / INVALID_REQUEST`를 반환했다. 기존 결함 두 요청의 `fieldErrors.field`는 각각 `page`, `size`이며 [FoodMaterials 로그](../.verification/54712d144fdf/FoodMaterialsService.log)에 `ConstraintViolationException`이 없다. NF-07 종료와 NF-08 종료의 5개 업무 테이블 스냅샷이 일치하여 오류 요청의 DB 불변도 확인했다.

전체 HTTP 292건(health 3건 포함)을 기록했다. [최종 DB 증거](../.verification/54712d144fdf/NF-12-database.json)는 카탈로그15·재고11·원장23·메뉴3·폐기13행이며 폐기 상태는 COMPLETED7/REJECTED6/PENDING0이다. 정상 재고 처리, 중복 폐기의 1회 차감, 계정 격리와 충돌 시나리오가 모두 통과했다.

G1/G2 모두 `cleanup.passed=true`, `remaining=[]`, `processLeak=[]`다. 종료 후 Docker의 검증 run label 컨테이너와 두 runId JVM을 다시 조회해 잔여 0을 확인했다. 기존 DB·볼륨·운영 환경에는 이번 검증 데이터를 쓰지 않았다. 이 결과는 로컬 G1/G2 증거이며 Gateway 전체 경로·G4 장애 복구·원격 CI의 완료를 뜻하지 않는다.

[Claude 최종 증거 검토 원본](../.verification/54712d144fdf/claude-result-review.md)은 **G1→G2 범위에서 PASS 판정이 타당하다**고 확인했다. 신규 회귀 6개의 JUnit XML, 현재 소스 해시, 292건 HTTP의 5xx/202/전송 오류 0건, 오류 입력의 DB 불변, 완료 폐기 7건과 원장 행의 1:1 대응을 독립 대조했다.

검토 의견 중 동시 중복 폐기에서 발생하는 MariaDB 1062·Hibernate WARN은 정상 중복 처리 경로의 로그이며 기능 결함은 아니라는 판단을 채택했다. 향후 관측 단계에서 경보 기준을 검토할 항목으로 남긴다. Claude의 Docker 직접 조회는 멈춰 중지돼 cleanup manifest까지만 독립 확인했고, 실시간 잔여 컨테이너·JVM 0건은 Codex가 별도로 조회한 결과다. 오류 응답의 fieldErrors 차이는 위 제품 검토에 명시했다. 이 검토는 이전 검증기 전체 코드의 재승인이 아니라 이번 제품 수정과 최종 실행 증거의 검토다.

## 수정 전 실행·독립 검토 결과

첫 실행에서 NF-02/04/05/06/07이 PASS였고 NF-08에서 위 결함을 발견했다. NF-09~12는 당시 fail-fast로 NOT_RUN이었다. 해당 실패 실행도 보존한다.

수정 전 최종 진단 실행은 [f442a239f322 manifest](../.verification/f442a239f322/manifest.json), [HTTP 기록](../.verification/f442a239f322/http.jsonl), [최종 합성 DB 증거](../.verification/f442a239f322/NF-12-database.json)에 있다. 실행 시간은 2026-09-28 16:15:18~16:16:33 KST다. 당시 manifest의 소스 해시를 수정 전 파일과 대조해 차이 없음을 확인했다. 제품 코드의 동일한 두 입력 오류가 재현됐으며, 보완된 검증기에서도 최종 FAIL이다.

| runId | 의미와 보존 상태 |
|---|---|
| `6a057254a96f` | 첫 실패. NF08에서 중단하여 이후 사례 NOT_RUN |
| `812c7a9fcc67` | 첫 전체 진단. Claude가 검토한 중간 코드의 9 PASS/1 FAIL. NF08은 당시 HTTP 상태만 검사 |
| `d7edfe9cbf8a` | 검토 보완 후 9 PASS/1 FAIL. 요청 시간 기록으로 포트 소유권 검사 뒤 출발 시점이 분산되는 것을 확인 |
| `f442a239f322` | 제품 수정 전 검증기 최종 코드. 소유권 검사 후 HTTP 직전 시작 장벽으로 조정하고 9 PASS/1 FAIL 및 요청 겹침 증거 확인 |

| 사례 | 결과 | 확인한 내용 |
|---|---|---|
| NF-02 | PASS | 3서비스 정상 토큰 대조, 인증 변형 7종의 GET·POST 42건 401, DB 불변 |
| NF-04 | PASS | 메뉴 CRUD·낡은 version 409·비활성화·상태필터·페이지 정렬 |
| NF-05 | PASS | 식자재 CRUD·낡은 version 409·SKU 중복 및 계정별 유일성·비활성화 |
| NF-06 | PASS | 재고 20→17→15, 조정 중복409, 폐기 재전송/retry200, 원장 3행·DB 일치 |
| NF-07 | PASS | 타 계정 상세·수정·비활성화·재시도404, 목록 분리, 타 계정 신규 폐기409/REJECTED |
| NF-08 | **FAIL** | 입력16건 중 식자재 page=-1/size=101 두 요청500. 나머지14건400, 업무 DB 불변 |
| NF-09 | PASS | 8개 동시 동일 폐기 3회: 동일 결과·1회 차감, payload 변경409 |
| NF-10 | PASS | 재고 부족·미등록 재고 거절, 보충 후 거절 retry 보존, 다른 폐기2개 경합3회 |
| NF-11 | PASS | 같은 version 조정10개 경합3회: 성공1·충돌9·원장1·재고19 |
| NF-12 | PASS | COMPLETED/REJECTED 상세·A/B 목록·필터·페이지와 DB 일치, PENDING 0 assertion |

HTTP 기록은 health 포함 292건, 업무·인증 요청은 289건이다. 카탈로그15·재고11·원장23·메뉴3·폐기13행을 최종 대조했고, 폐기는 COMPLETED7/REJECTED6/PENDING0이었다. 4개 schema의 Flyway 성공 이력을 확인했다. 이 개수는 이번 합성 fixture의 결과이며 운영 처리 실적이 아니다.

[동시 요청 시간 대조](../.verification/f442a239f322/concurrency-evidence.json)는 HTTP 기록의 시작·종료 시각으로 계산한 파생 증거다. NF09의 8개, NF10의 2개, NF11의 10개 요청이 각 3회 모두 클라이언트 관측 구간에서 겹쳤다. 전체 요청이 겹치는 시간은 각각 약19.3~19.7ms, 16.9~17.7ms, 8.3~8.9ms다. 이는 시작 장벽과 실제 요청 겹침의 증거이며, 서버 내부의 모든 트랜잭션이 같은 순간 실행됐다는 주장이나 성능 측정값은 아니다.

안전성·판정 단위 검사 9개와 G0 기본·CI·performance 정적 검사 3종은 PASS다. 최종 실행은 `cleanup.passed=true`, `remaining=[]`, `processLeak=[]`다. 이전 실행의 정리 기록도 각 manifest에 보존했다. 이 검증기 구현 단계에서는 기존 DB/볼륨·제품 소스·Compose·Jenkins를 수정하지 않았다. 이후 제품 예외 처리 수정은 위 G2-FIX-01에 별도로 기록했다.

Claude(`g2-reviewer`, Herdr `w5:p9`)는 같은 cwd·HEAD에서 코드·계약·첫 두 실행 기록을 읽었다. [원본 검토](../.verification/812c7a9fcc67/claude-review.md)에서 **기존 9 PASS를 뒤집는 거짓 PASS를 찾지 못했고, 전체 FAIL 및 제품 결함 원인은 타당하다**고 보고했다. JDBC가 임시 loopback 4개 schema에만 연결됐고 Eureka 접속 흔적이 없다는 점도 로그로 확인했다. 기존 Claude `w5:p2`의 미전송 초안을 보존하기 위해 별도 검토 창을 사용했다.

### 독립 검토 의견 반영

| 검토 항목 | Codex 판단·반영 |
|---|---|
| 1-1 / 잘못된 입력의 DB 변경은 BLOCKED가 아닌 FAIL | 채택. `FatalFailure`로 FAIL을 기록하고 후속 진단은 중단 |
| 1-2 / 비JSON 응답에서 HTTP 증거 소실 | 채택. 상태를 먼저 기록하고 원문을 비밀값 제거 후 보존, 계약 실패로 판정 |
| 1-3 / 임시 포트 경쟁·JVM 종료 | 채택. readiness부터 매 HTTP 요청 전 PID 생존 및 `lsof` listener 소유권 대조 |
| 1-4 / credential과 JVM 작업 디렉터리 분리 | 채택. 개인키 별도 임시 폴더, 공개키만 복사, DB env 즉시 제거. OS 사용자 경계의 한계 명시 |
| 1-5 / DB 조회 전용 권한 | 채택. verifier에 SELECT만 부여, 다중 문장·개행·역슬래시 거부 |
| 1-6 / G1 비교에서 scripts 전체 제외 | 채택. 신규 G2 파일 3개만 제외하고 키 생성기·정적 검사기를 포함해 대조 |
| 1-7·1-8 / 로그·스냅샷 수집 예외 | 채택. 로그 복사 실패에도 정리 지속, 원래 사례 오류와 증거 수집 오류를 별도 보존 |
| 2-1 / HTTP 외 오류 code 검사 | 채택. NF08은 INVALID_REQUEST, NF02는 AUTHENTICATION_REQUIRED/INVALID_ACCESS_TOKEN 대조 |
| 2-2·2-3 / PENDING 부재 및 B 목록 | 채택. NF12에서 최종 폐기 상태 불변식과 A/B 목록·상태필터·페이지 검사 |
| 2-4 / 동시 요청 시간 증거 | 채택. 요청별 startedAtNs/finishedAtNs 기록 |
| 2-5 / 설계 예시 fixture와 값 차이 | 의미에 영향 없는 차이로 문서화. G2 메뉴 가격1000→2500, SKU MAT-runId-n 사용. G2 기대값과 실제값은 이 fixture로 일치 검사 |
| 2-6 / 상태 전이·증거 처리 테스트 | 채택. FAIL 이후 독립 진행, 의존 사례 NOT_RUN, 인증 실패 중단, DB 변경 FAIL, 비JSON 보존 및 집계 검사 추가 |
| 2-7 / migration 준비 실패 | 채택. 사례 실행 전 환경 조건 실패는 BLOCKED |

같은 소스 입력의 재현 가능한 JAR는 재빌드해도 SHA-256이 같을 수 있다. 이번 실행에서 새로 빌드됐다는 근거는 `--rerun-tasks`, 빌드 종료 코드, mtime, 임시 복사본이며 SHA-256은 해당 바이트의 식별·변경 감지 근거다.

이 표는 Claude 원본 의견을 Codex가 판단해 반영한 기록이다. 반영 후 코드 전체의 Claude 재승인을 의미하지 않으며, 보완 후 실행 결과는 위 최종 manifest로 구분한다. 오류 응답 재현 범위·입력별 code·DB 불변·시간 대조와 정리는 Codex가 최종 코드에서 다시 확인했다.

## 다음 단계

제품 수정과 G1→G2 재검증을 완료했다. 남은 단계는 G3 Gateway 전체 경로의 구현·실행이며 G3/G4는 아직 미실행이다. Annotate에서는 실제 변경한 예외 처리와 회귀 범위, 수정 전후 실행 증거를 검토한다.
