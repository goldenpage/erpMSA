# ErpMSA 정상 흐름 검증 상세 설계

> 설계 기준: v1 · Claude 독립 검토 의견 반영 완료 · Annotate 검토 가능. 현재 실행 상태는 아래 후속 기록 참조.
> 설계: Codex · 독립 검토: 같은 Herdr 작업 폴더의 Claude (`w5:p2`)
> 기준: 2026-09-21 / `feat/status` / `d11461b52a0e2cb90521b3217d55f960d4c0676e`
> 경로: `/Users/jonghwan/.herdr/worktrees/ErpMSA/feat-status`

> 후속 진행(2026-09-28): 사용자의 진행 요청에 따라 격리 환경·G1 및 G2 구현과 실행을 진행했다. 아래 본문은 설계 당시 범위·판정 기준이며 현재 증거는 [G1 실행 기록](g1-verification-results.md)과 [G2 실행 기록](g2-verification-results.md)을 따른다. G2에서 발견한 입력 오류 응답 결함을 구현·수정했고 G1 119개 및 G2 10개 시나리오가 모두 PASS다. G3/G4는 실행하지 않았다.

## 1. 이번에 확정할 범위

[전체 통합 검증 계획](integration-verification-plan.md)의 **G1 서비스별 회귀 → G2 실제 3서비스 → G3 Gateway 전체 경로**를 실행 가능한 절차와 판정 기준으로 구체화한다. 환경 격리와 G0 정적 계약은 진입 조건, 결과 수집과 전용 자원 정리는 종료 조건이다.

이 본문은 설계 당시 범위를 보존한다. 이후 사용자 요청으로 G1/G2 실행기·회귀 테스트·발견 제품 결함의 수정까지 진행했으며, 최신 구현·실행 상태는 위 후속 기록을 따른다.

여기서 정상 흐름은 의존 서비스가 가동 중인 상태다. 성공 응답 외에도 입력·인증·소유권·충돌·재고 부족에 따른 400/401/404/409와 미구현 서비스의 501을 포함한다. **G4의 서비스 중지·응답 변조/유실·강제 종료·PENDING 복구는 제외**한다. G1의 기존 모의 실패 회귀 테스트는 그대로 포함하되 실제 G4 수행 증거로 집계하지 않는다.

| Annotate 결정 ID | 제안 |
|---|---|
| NF-DEC-01 | G1/G2/G3별 결과를 분리하고, 모든 정상 단계가 통과해야 G4 착수 가능 상태로 보고 |
| NF-DEC-02 | 정상 업무는 API로 만들고, 전용 DB의 읽기 조회로 폐기·재고·원장 결과를 대조 |
| NF-DEC-03 | 정상 시나리오의 예상 밖 202/5xx를 자동 재시도로 숨기지 않고 첫 실패를 보존 |
| NF-DEC-04 | 실행별 격리 환경·계정·fixture·증거 묶음 사용, 기존 성능 실험실과 Jenkins 환경 재사용 금지 |

서비스 명칭·포트·기본 경로는 [services.json](../architecture/services.json)을 유지한다. Menus는 메뉴 CRUD·비활성화, FoodMaterials는 카탈로그와 내부 재고, Disposals는 폐기·재고 차감이다. Notices·Bills·Purchase는 501 계약만 검사한다. 새로운 업무 기능이나 Inventory/Audit/Order 서버를 설계하지 않는다.

## 2. 준비 조건과 단계 경계

### 2.1 실행별 격리 환경의 설계

실행기는 향후 `runId`와 단계 식별자 G1/G2/G3를 발급하고, 소스 SHA·실행 시각·자원 ID·이미지 ID·fixture 식별자를 manifest로 연결한다. G2와 G3는 서로 다른 데이터 저장소를 사용한다.

runId는 실행마다 새로 생성하는 소문자 16진수 12자리로 제한한다. `CI_PROJECT_NAME=erpmsa-it-<runId>-g3`, `BUILD_NUMBER=<source-id>`, `JWT_SIGNING_KEY_ID=it-<runId>`를 필수 주입한다. source-id는 검증한 소스 revision의 짧은 16진수 식별자이며 실제 전체 SHA와 image ID는 manifest에 남긴다. 전송 파일명·공개키 kid·Account의 렌더된 `JWT_PRIVATE_KEY_PATH=/run/jwt-private/it-<runId>.pem`이 서로 일치해야 기동한다.

| 항목 | 구현할 규칙 / 확인 증거 |
|---|---|
| G1 | 기존 Testcontainers가 생성한 MariaDB/Redis/Kafka만 사용. 재사용 컨테이너 기능을 켜지 않음. Docker 접속은 검증한 로컬 context만 사용 |
| G2 | [기존 직접 JAR 검증기](../scripts/verify-menu-disposal-flow.py)의 고유 컨테이너·tmpfs·임시 포트·임시 키 방식. 3개 JAR가 해당 실행의 빌드 산출물인지 hash로 확인 |
| G3 | `erpmsa-it-<runId>-g3` Compose 프로젝트와 전용 네트워크. 기본 Compose + CI 격리 override + 향후 생성할 임시 override 사용 |
| Compose 이름 | `-p` 값과 `CI_PROJECT_NAME`을 위 프로젝트명으로 일치시킴. named volume은 모두 `<project>-` 접두사, external 금지. image 태그도 `<project>/<service>:<source-id>`로 격리 |
| DB/캐시/브로커 | MariaDB `/var/lib/mysql`, Redis `/data`, Kafka `/tmp/kraft-combined-logs` tmpfs 확인. 프로젝트 label·mount·주소를 확인하기 전 쓰기 fixture 금지 |
| 키·환경변수 | 실행기에서 임시 RSA 키 생성, 공개/개인키를 전용 볼륨으로 stdin 전송. Account만 개인키 마운트, 검증 서비스는 공개키만 읽기 전용. CI 키 전송 방식을 참고하며 실제 키 파일·토큰은 보고서에서 제외 |
| 환경 상속 | 기존 `.env`/성능 `.env`를 읽지 않음. 실행 전용 env를 명시하고 Spring datasource/JVM/JWT의 외부 override를 배제. Docker 접속 관련 값도 로컬 daemon 검증 후 필요한 값만 전달 |
| 접속 | 호스트에는 Gateway·Prometheus·Grafana의 loopback 임시 포트만 노출. 서비스 직접 health/JWT 검사는 전용 네트워크의 임시 probe로 수행. Kafka record 검사도 내부 `kafka:9092` 사용 |
| 기동 준비 | CI 키 볼륨을 먼저 채우고 비루트 사용자의 읽기 권한을 검사. MariaDB health 및 database-init 종료 코드 0, migration 성공 후 업무 readiness 검사. 모든 테스트 애플리케이션 restart=no |
| 종료 | 생성 목록과 프로젝트 label로 자신의 자원만 정리. 증거 수집 후 삭제하며 기존 볼륨·공유 이미지·Jenkins 네트워크는 건드리지 않음 |

키 전송은 [기존 키 전송 검증기](../scripts/verify-ci-key-transfer.sh)의 방식만 참고한다. 이 스크립트의 고정 fixture를 G3 실행 키로 사용하거나 현재 실행하지 않는다. G3 임시 override가 아직 없으므로 현재 Compose 명령 한 줄로 위 환경을 완성할 수 있다고 주장하지 않는다.

임시 네트워크 probe와 Kafka 소비 도구는 검증 전용 도구다. 업무 서비스 목록이나 정규 Compose/Eureka에 새로운 서버를 추가하지 않는다. 생성 helper에도 실행 label을 붙이고 종료 시 목록을 대조한다.

실행 env는 `JWT_SIGNING_KEY_ID`를 생성한 키의 kid와 맞추고, 모든 서비스의 issuer/audience를 동일하게 고정한다. Account의 `FLYWAY_BASELINE_ON_MIGRATE=false`, FoodMaterials의 두 baseline-on-migrate=false, JPA validate도 렌더 결과로 확인한다. 기본 Compose의 Account baseline 기본값 true를 그대로 상속하지 않는다. 기존 실행 설정은 수정하지 않고 향후 임시 env에만 적용한다.

### 2.2 G0~G3 순서와 전이 조건

| 순서 | 수행 설계 | 다음 단계 진입 조건 |
|---|---|---|
| S0 | 소스/도구 버전, 변경 파일 목록, 자원 격리 계획 확인. 기존 아키텍처 검사 기본·CI·performance 실행 | 3종 PASS. 향후 임시 override는 별도 렌더 검사로 볼륨/키/포트/정확한 서비스 집합 확인 |
| S1 / G1 | 9개 Spring 프로젝트의 Gradle test와 NF-13의 독립 migration fixture 검증을 순차 실행 | 해당 실행의 XML에서 프로젝트 누락·실패·오류·필수 SKIP 없음. NF-13 보완 미구현은 통과로 집계하지 않음 |
| S2 / G2 | FoodMaterials/Menus/Disposals bootJar 빌드 후 실제 HTTP·임시 DB 직접 연동 | §4의 G2 대상 사례 PASS. JWT는 전용 서명 fixture, discovery=false라는 실행 범위를 명시 |
| S3 / G3 준비 | 전용 전체 스택 빌드/기동, API 읽기 readiness, 준비 계정 생성 | 기대 Eureka 7개와 업무 경로 7개의 응답이 안정화 |
| S4 / G3 | Account 발행 토큰으로 §4의 G3 사례 실행. 재고 호출은 기본 discovery=true 유지 | HTTP·업무 상태·DB·이벤트·관측 증거 모두 일치 |
| S5 / 종료 | 단계별 결과표, 실패 진단, 비밀값 제거, 전용 자원 정리 | 증거 및 정리 누락 없이 정상 범위 완료. 전체 통합/G4/원격 CI 완료로 확대하지 않음 |

G1 대상은 `eurekaServer`, `gatewayServer`, `AccountService`, `MenusService`, `FoodMaterialsService`, `NoticesService`, `BillsService`, `PurchaseService`, `DisposalsService`다. 각 wrapper와 Java 21 및 현재 build.gradle을 사용하고 라이브러리를 업그레이드하지 않는다. 서비스 Gradle 의존 관계로 공유 모듈도 빌드한다.

G1 구현 시 명령 형태는 `<module>/gradlew -p <module> test --no-daemon --rerun-tasks`다. 정해진 9개 module만 허용하고 실행 전 환경을 제한한다. 기존 XML을 현재 실행으로 오인하지 않도록 시작 시각·실행 task·현재 XML을 함께 기록한다. 기존 테스트의 DB fixture 삭제는 Testcontainers 소유 DB에서만 허용하며 애플리케이션 DB 주소를 주입하지 않는다. 테스트 수는 과거의 고정 숫자 대신 현재 수집된 suite/case 목록과 실행 수로 대조한다.

G2/G3 빌드 산출물은 같은 소스 기준이어야 한다. 빌드·의존성 확보·Docker 문제는 BLOCKED, 실행된 테스트의 assertion 실패는 FAIL로 분리하고 선행 단계 실패 시 후행 단계는 NOT_RUN으로 남긴다. 이미 존재하는 JAR/이미지를 이름만 보고 재사용하지 않는다.

### 2.3 G3 준비 검사

인프라 health와 TCP 포트가 열렸다는 사실만으로 완료하지 않는다. 각 서비스 `/actuator/health`의 HTTP 200·body status=UP, migration 성공, Eureka의 **기대 이름 7개가 각 1개 UP**인 것을 확인한다. Gateway와 Eureka는 등록 대상이 아니며 9개 Spring 모니터링 대상과 구분한다.

`GET /account/auth/login`의 405로 Account 라우트 도달을 먼저 확인한 뒤, 준비용 계정 R을 API로 한 번 가입·로그인한다. R의 토큰으로 `/account/auth/me`, `/menus`, `/foodmaterials`, `/disposals`는 200, `/notices`, `/bills`, `/purchase`는 501+정확한 service/code를 확인한다. 모든 경로가 1초 간격으로 연속 3회 기대 응답이면 준비 완료다. 준비용 R은 아래 A/B fixture와 분리한다.

405는 코드 경로에서 기대하는 라우트 도달 신호이며 이번에 실제 실행으로 확인한 응답이 아니다. 405만으로 인증이나 전체 업무 readiness를 통과시키지 않는다. 기대 405 대신 401/404가 지속되면 준비 실패로 기록하고 Gateway/Account 응답과 로그로 원인을 분류한다. HTTP 상태 하나만으로 원인을 단정하지 않는다.

기동은 180초, 기동 후 라우트 안정화는 별도 180초 한도로 제안한다. 따라서 두 단계의 합을 180초로 보고하지 않는다. 읽기 요청마다 최대 15초와 단계의 남은 시간을 함께 적용해 전체 deadline을 넘기지 않게 한다. 단순 401은 인증 필터 응답일 수 있으므로 라우팅 증거로 사용하지 않는다.

## 3. Fixture와 기본 업무 여정

### 3.1 요청 자료

G3의 각 독립 사례/반복은 자기 소유의 합성 계정 A/B와 requestId를 갖는다. 준비 계정 R, 인증 회전 계정, 이벤트 전용 계정도 분리한다. G2는 같은 개념의 합성 accountId와 전용 JWT를 사용하며 Account 가입 검증으로 집계하지 않는다.

| 요청 | 데이터 규칙 |
|---|---|
| 가입 | `email=it-<runId>-<case>-a@example.com`, 유일한 10자리 숫자 businessId, 실행기 생성 비밀번호(8~100자), name/storeName 필수. phone 등 선택 필드는 합성값 또는 생략, marketingAgreed=false |
| 로그인 | email/password. A/B별 cookie jar·Access/Refresh를 분리하고 토큰 값은 출력하지 않음 |
| 메뉴 생성/수정 | 생성 name·description·price=12000. 수정은 변경한 name·description·price=13000·status=ACTIVE·응답에서 얻은 version. DELETE는 비활성화 |
| 식자재 생성/수정 | sku=`IT-<SHORT-RUN>-<CASE>`(대문자·숫자·하이픈만 사용, 64자 이내), name·unitPrice=1000. 수정은 name·description·unitPrice·status·응답 version. SKU는 수정 DTO에 넣지 않음 |
| 재고 생성/조정 | foodMaterialId·initialQuantity=20. 조정은 requestId·quantityDelta=-3·reason·현재 version |
| 폐기 생성 | requestId(64자 이내)·foodMaterialId·quantity=2·reason. 일반 조정 ID와 분리하며 내부 명령 ID는 서버의 `DISPOSAL-{disposalId}` 사용 |

DTO 근거: [가입](../AccountService/src/main/java/com/oopsw/accountservice/advice/dto/RegisterRequest.java), [메뉴](../MenusService/src/main/java/com/oopsw/menusservice/menu/MenuController.java), [식자재 수정](../FoodMaterialsService/src/main/java/com/oopsw/foodmaterialsservice/web/dto/UpdateFoodMaterialRequest.java), [재고 조정](../FoodMaterialsService/src/main/java/com/oopsw/foodmaterialsservice/inventory/web/dto/AdjustInventoryRequest.java), [폐기](../DisposalsService/src/main/java/com/oopsw/disposalsservice/disposal/DisposalController.java).

ID와 version은 응답에서 읽는다. accountId=1·초기 version=0 같은 환경 의존값을 G3에 고정하지 않는다. 금액은 JSON 표현의 문자열 동일성이 아닌 수치로 비교한다. fixture의 ID·sku·email은 길이와 중복을 검증한 뒤 사용한다.

SKU 응답은 [FoodMaterialsService](../FoodMaterialsService/src/main/java/com/oopsw/foodmaterialsservice/service/FoodMaterialsService.java)의 `trim().toUpperCase(Locale.ROOT)` 결과와 비교한다. NF-05의 중복 검사는 A의 같은 SKU와 대소문자만 바꾼 SKU가 모두 409인 것을 포함한다. B의 동일 SKU는 별도 소유 자료로 201이므로 이를 전역 중복이라고 판정하지 않는다. 이 추가 자료도 B의 시나리오 fixture 목록에 기록한다.

### 3.2 FLOW: 식자재→재고 조정→폐기 여정

이 여정은 G2와 G3에서 각각 새 fixture로 실행한다. G3의 아래 요청은 모두 Gateway를 경유하며, 마지막 DB 조회만 전용 DB에 직접 수행한다.

| 단계 | 요청 / 기대 응답 | 재고와 원장 기대값 |
|---|---|---|
| F1 | A 식자재 POST `/foodmaterials` → 201, foodMaterialId 저장 | 카탈로그 1행 |
| F2 | POST `/foodmaterials/inventories` initialQuantity=20 → 201 | 현재고 20, INITIAL 1행 |
| F3 | POST `/foodmaterials/inventories/{id}/adjustments` -3 → 200 | 현재고 17, 해당 ADJUSTMENT 1행 |
| F4 | 같은 조정 requestId 재전송 → 409 ADJUSTMENT_ALREADY_EXISTS | 여전히 17, 새 원장 없음 |
| F5 | POST `/disposals` quantity=2 → 200/COMPLETED | 현재고 15, 해당 DISPOSAL 1행, 폐기 1행 |
| F6 | F5와 같은 POST 및 `/disposals/{disposalId}/retry` → 각각 200/COMPLETED | 같은 disposalId/movementId/quantityAfter=15, 추가 차감 없음 |
| F7 | 재고·원장·폐기 상세/목록 GET → 200, DB 읽기 대조 | INITIAL/ADJUSTMENT/DISPOSAL 각 1행, 총 3행, 20→17→15 연속성 |

메뉴의 생성·수정·비활성화는 별도 fixture에서 검사한다. 메뉴 처리에 따른 식자재 소모나 레시피 연동을 이 여정에 추가하지 않는다.

## 4. 정상 범위 시나리오와 상위 계획 대응

아래 각 행은 필수다. G2 칸이 제외인 것은 그 단계의 역할 밖이라는 의미이며, G3의 같은 사례가 생략되는 것은 아니다. `기존 일부`는 재사용 가능한 코드가 있지만 표 전체를 자동 검증하는 완성 실행기가 있다는 뜻은 아니다.

| ID / 상위 사례 | G2 / G3 | 절차와 필수 판정 |
|---|---|---|
| NF-01 / AUTH-01 | 제외 / 필수 | 가입201→로그인200→me200/계정 일치→Refresh200 회전→이전 Refresh401→logout204→회전된 Refresh 재사용401. Access 즉시 폐기 요구 없음 |
| NF-02 / AUTH-02 | 3서비스 / 7서비스+Gateway | 정상 신뢰 토큰 대조 뒤 미인증·만료·issuer/audience 오류·잘못된 서명·미등록 kid·Refresh Bearer가 401. 음성 입력 시 DB 불변 |
| NF-03 / ROUTE-01·SHELL-01 | 제외 / 필수 | 정상 7경로, 미구현 3서비스는 501+ENDPOINT_NOT_IMPLEMENTED+해당 service. 유효 토큰의 `/items`·`/inventories`·`/orders`는 404 |
| NF-04 / MENU-01 | 필수 / 필수 | 생성201→상세/목록200→값을 바꾼 수정200→낡은 version 수정409 MENU_CONFLICT→삭제204→상세 INACTIVE·DB 행 보존. 상태필터·createdAt/id 내림차순·페이지 중복/누락 확인 |
| NF-05 / FOOD-01 | 필수 / 필수 | 생성201·상세/목록200·수정200·낡은 version409 FOOD_MATERIAL_CONFLICT·동일 SKU409 SKU_ALREADY_EXISTS·삭제204→INACTIVE. foodMaterialId/foodMaterials 필드 확인 |
| NF-06 / INV-01·DISP-01 일부 | 필수 / 필수 | §3.2 FLOW 전체 수행. 일반 조정 중복409와 폐기 재전송 기존결과200을 구별하고 3개 원장과 두 DB를 대조 |
| NF-07 / TENANT-01 | 필수 / 필수 | B의 A 리소스 상세/수정/비활성화/retry는 해당 계약404, 목록에 A 소유 행 없음. B의 A 식자재 신규 폐기는 409/REJECTED·INVENTORY_NOT_FOUND, B 거절행1·A 재고/원장 불변 |
| NF-08 / INPUT-01 | 필수 / 필수 | 메뉴 음수 가격·필수 name 누락, 폐기 quantity 0/-1·requestId 65자·reason 256자, page=-1/size=101 →400. 실패 요청이 행/원장을 추가하지 않음 |
| NF-09 / DISP-01·02 | 필수 / 필수 | 새 재고20에서 같은 quantity3 폐기 8개 동시 POST→전부200/COMPLETED·동일 ID·재고17·폐기1·명령원장1. 이후 동일 requestId의 수량/식자재/사유를 각각 변경→409 REQUEST_CONFLICT·기존행 불변 |
| NF-10 / DISP-03·07 | 필수 / 필수 | 재고20에서 quantity21→409 REJECTED/INSUFFICIENT_STOCK. 미등록 재고→409 REJECTED/INVENTORY_NOT_FOUND. 별도 재고20에 서로 다른 quantity15 요청2개 동시→200 1개·409거절1개·재고5·차감원장1개 |
| NF-11 / INV-01 | 필수 / 필수 | 별도 재고20의 같은 version으로 requestId가 다른 -1 조정10개 동시→200 1개·409 INVENTORY_CONFLICT 9개·재고19·새 ADJUSTMENT1개 |
| NF-12 / DISP-10 부분 | 필수 / 필수 | 자기 COMPLETED/REJECTED 상세200 및 목록/각 상태필터200, createdAt/id 내림차순과 페이지 일치. PENDING 필터 생성/복구 부분은 G4 보류 |
| NF-13 / DB-01 | G1에서 검증 / G3 신규환경 확인 | G1의 독립 과거 V1 fixture와 migration 후 데이터/이력 보존. G3는 5개 schema의 소유 서비스 migration 완료·catalog/inventory 테이블 혼입 없음. 상세 기준은 §5 |
| NF-14 / EVENT-01 | 제외 / 필수 | 이벤트 전용 계정 등록 후 해당 eventId의 Outbox PUBLISHED·Kafka record 최소1개·schema/key/payload 대조. 계정/준비 fixture의 다른 이벤트는 제외 |
| NF-15 / OBS-01 | 제외 / 필수 | 9개 Spring target의 scrape 성공·지표 표본, 통제된 요청 전후 HTTP count 증가, Grafana datasource 연결 및 dashboard 구성 확인. 화면 렌더 품질은 별도 미확인 |

NF-02는 G3에서 Gateway 보호 경로와 전용 네트워크를 통한 각 서비스 직접 보호 경로를 모두 검사해 Gateway의 401만으로 하위 서비스 인증을 증명하지 않는다. 정상 G3 업무 여정은 직접 호출로 우회하지 않는다.

신뢰된 실행 키/kid로 정상 대조 토큰을 먼저 검사하고 각 변형에서 검사 대상 claim만 바꾼다. 만료 exp는 검사 시각보다 최소 60초 과거로 두어 30초 leeway를 넘긴다. 잘못된 서명은 정상 kid를 유지한 채 다른 키로 서명한다. 음성 JWT fixture와 실제 Account 발급 Access의 결과를 별도 기록한다. NF-01의 Refresh cookie는 HttpOnly·SameSite=Strict·Path=/account/auth를 확인하며 Secure는 격리 HTTP 환경의 COOKIE_SECURE=false와 대조한다. 운영 쿠키 설정을 바꾸는 지시가 아니다.

NF-07의 타 계정 재고 조정에는 **B에게 아직 없는 requestId와 유효한 입력**을 사용한다. [InventoryService](../FoodMaterialsService/src/main/java/com/oopsw/foodmaterialsservice/inventory/service/InventoryService.java)는 중복 requestId를 소유권 조회보다 먼저 검사하므로 중복409를 소유권404 검증으로 오인하지 않게 한다.

NF-09/10의 동시 폐기와 NF-11의 조정 경합은 각 3회, 매번 새 fixture로 실시한다. 정상 상태에서 시작 장벽으로 요청을 모은다. NF-10의 첫 번째 사례(20에서 quantity21 거절)에서 정상 +2 조정으로 재고를 22로 만든 뒤 같은 거절 폐기를 retry해도 REJECTED·재고22가 유지되는지 추가 확인한다. 미등록 재고 사례와 동시 quantity15 사례는 다른 fixture로 수행한다. 보충 조정으로 생긴 원장은 폐기의 차감으로 집계하지 않는다.

## 5. DB·이벤트 대조 방법

G2/G3의 쓰기 fixture는 API로 생성하고, 결과 대조는 격리 확인을 마친 DB에 읽기 전용 SQL로 수행한다. G1은 전용 Testcontainers 안의 기존 SQL fixture·정리·동일 시각 정렬 fixture와 DB-01의 과거 schema/합성 데이터 준비를 허용한다. 테스트 SQL로 실행된 서비스 결과를 고치거나 PENDING을 완료로 바꾸지 않는다.

| 대상 | 대조 기준 |
|---|---|
| 폐기 | disposalsdb.disposal을 account_id/request_id로 한정. id/status/movement_id/quantity_after와 API 결과 대조 |
| 재고 | inventorydb.inventory를 account_id/item_id로 한정. DB의 item_id가 공개 API의 foodMaterialId에 대응. 수량·version 대조 |
| 원장 | inventorydb.stock_movement를 account_id/request_id로 한정. 폐기는 `DISPOSAL-{disposalId}`, ADJUSTMENT는 클라이언트 requestId. movement_type/delta/before/after 및 FK 일치 |
| 불변식 | 다른 쓰기가 없는 fixture에서 초기수량 + 원장 delta 합 = 현재고. INITIAL을 합에 포함할 때는 0 + 전체 원장 delta 합으로 계산해 초기수량을 두 번 더하지 않음 |
| migration | mydb(Account), itemdb(FoodMaterials catalog), inventorydb(FoodMaterials 내부 재고), menusdb, disposalsdb의 Flyway 성공 이력. shell 3서비스에 새 DB를 요구하지 않음 |
| Outbox/Kafka | mydb.account_outbox_event에서 event_key=accountId 십진 문자열 AND event_id=eventId(UUID)로 한정, aggregate_id도 같은 계정 문자열인지 확인. status=PUBLISHED·published_at IS NOT NULL. Kafka key는 event_key와 동일, 토픽은 설정값, payload는 해당 Outbox payload 및 schema와 대조 |

DB-01은 [상위 문서의 과거 revision·SQL hash](integration-verification-plan.md)의 V1 blob으로 별도 임시 DB를 준비한다. 고정 legacy 재고 fixture 예시는 ID77/account101/material777/수량42/version3/초기원장1개다. 카탈로그도 별도 합성 ID/SKU/소유자/값을 넣고 현 migration 전후를 대조한다. 현재 V1 파일로 이전 schema를 만들기만 한 테스트를 독립 이력 검증으로 집계하지 않는다. 과거 blob을 못 얻으면 BLOCKED다.

기존 [재고 migration 테스트](../FoodMaterialsService/src/test/java/com/oopsw/foodmaterialsservice/inventory/InventoryMigrationCompatibilityTest.java)는 재고 보존 일부를 다루며 독립 Git blob fixture·카탈로그 보존 보완은 아직 구현되지 않았다. G1 기존 테스트 PASS만으로 NF-13 전체를 PASS 처리하지 않는다.

NF-13의 독립 검증은 후속 구현 요청 시 **FoodMaterialsService의 테스트 fixture/테스트 보완**으로 진행하는 설계다. 결과는 `G1-existing`과 `NF-13-legacy`로 나눠 기록하고, 후자가 미구현이면 NOT_RUN이며 정상 범위 전체도 미완료다. 설계 문서의 작성 완료와 이 실행 완료 조건은 별개다. 현재 승인 범위에서는 테스트 코드를 추가하지 않는다.

후속 NF-13 구현은 고정 Git revision의 원본 V1 blob을 임시 migration 위치로 추출하고, 프로젝트가 사용하는 Flyway로 V1까지 migrate하여 실제 schema history/checksum을 생성한 뒤 합성 데이터를 넣는 방식으로 구체화한다. 이후 현 migration을 적용해 데이터와 기존 이력을 대조한다. SQL DDL만 mariadb 클라이언트로 실행하거나 baseline/repair로 이력을 대신 만드는 방법은 독립 Flyway 이력 검증으로 채택하지 않는다.

Outbox 테이블에는 account_id 컬럼이 없다. 최초 조회는 [AccountEventOutbox](../AccountService/src/main/java/com/oopsw/accountservice/outbox/AccountEventOutbox.java)가 넣는 event_key/aggregate_id로 대상 등록 이벤트를 찾고 event_id를 얻은 뒤, 위 복합 조건으로 추적한다. 조회 조건의 accountId는 시험 계정의 API 반환값이지 DB 컬럼 이름이 아니다.

Kafka는 등록 전 토픽 파티션별 시작 offset을 기록하고 해당 실행의 record만 읽는다. 별도 진단용 소비자는 고유 group을 쓰고 기존 group offset을 변경하지 않는다. Outbox 조회에서 얻은 eventId로 필터링하고 [JSON schema](../contracts/account-registered-v1.schema.json)의 required/타입/eventVersion 및 uuid/date-time format을 검사한다. additionalProperties=true와 별개로 비밀번호·토큰·개인키·이메일·전화번호 미포함도 확인한다. 최소 1개 record를 요구하며 동일 eventId 중복을 exactly-once 실패로 판정하지 않는다. Kafka/Outbox 대기는 180초 한도다.

## 6. 실행기 구성과 재사용 범위

이 표는 **향후 구현할 책임 분리**이며 파일·서비스를 지금 추가한 목록이 아니다.

| 책임 | 기존 자산 / 필요한 보완 |
|---|---|
| 환경/소유권 관리 | Compose CI 격리 규칙 및 키 전송 방식 재사용, 실행별 env/override/manifest/cleanup 소유권 검사 추가 |
| G1 실행·수집 | 각 Gradle wrapper와 테스트 재사용, suite 목록·실행 시각·XML·누락 검사 및 독립 migration fixture 보완 |
| G2 직접 실행 | verify-menu-disposal-flow.py의 tmpfs/JAR 기동 재사용. 현재 일부 메뉴/폐기 사례만 있으므로 NF 대상 확장, 실패 로그를 임시 디렉터리 삭제 전에 보존 |
| G3 업무 실행 | performance/smoke.py와 Jenkinsfile의 계약 참고. 고정 lab·users.json·전역 Outbox 개수 의존을 제거한 실행별 fixture/주소 입력 필요 |
| DB/이벤트/관측 대조 | 읽기 전용 verifier와 제한된 Kafka 수집, target별 metric 결과, token/secret 제거한 증거 수집 추가 |

실행 상태는 `준비 → G1 → G2 → G3 → 증거 수집 → 정리 → 보고`다. 업무 쓰기 요청은 기본 1회이며, 표에 명시한 멱등 재전송만 수행한다. 비멱등 생성 요청의 응답이 유실되면 fixture 식별자로 DB를 읽어 생성 여부를 진단하고 FAIL로 남긴다. 자동 재전송하여 정상 성공으로 덮어쓰지 않는다.

정상 NF 사례에서 예상 밖 202/PENDING 또는 5xx가 나오면 그 응답과 두 DB 상태를 보존하고 해당 사례를 FAIL 처리한다. PENDING을 실패 확정이나 완료로 쓰지 않으며 수동 상태 변경도 하지 않는다. 여기서 FAIL은 정상 검증 시나리오가 기대대로 끝나지 않았다는 뜻이다. G4의 PENDING 복구 계약 자체가 실패했다고 단정하지 않는다.

## 7. 완료 조건과 검토 기록

### 7.1 정상 범위 완료 판정

- G0 정적 검사, G1 현재 suite 실행과 migration 보완, G2/G3 대상 NF-01~15가 모두 PASS이고 필수 SKIP/누락/증거 누락이 없어야 한다. G2 제외 사례는 G3 결과로 확인한다.
- 단계마다 HTTP·body 상태·fixture별 DB 대조 결과를 기록한다. 전용 자원 정리가 실패하면 정상 범위 완료로 표시하지 않고 남은 ID를 보고한다.
- manifest에는 runId, 기준 SHA 및 변경 목록, 도구 버전, JAR/image hash, 시작/종료 시각, 테스트별 상태, 익명화한 request/disposal/event 식별자, XML/로그/DB 대조 증거 경로를 담는다. 비밀번호·토큰·Cookie·개인키는 제외한다.
- 이 문서의 범위가 통과하면 **정상 범위 완료 / G4 착수 가능**으로만 보고한다. 전체 계획의 DISP-04~06·08~09, DISP-10의 PENDING 부분, EVENT-02·OBS-02는 후속 범위로 명시하며 전체 통합 검증 상태는 미완료로 유지한다. 원격 Jenkins와 배포/운영도 별도 미확인이다.

### 7.2 이번 설계 작업의 사실과 미확인

현재 소스 HEAD는 상단 기준과 동일하다. 기존 상위 설계 문서가 untracked인 상태에서 시작했으며 그 파일을 구현 결과로 취급하지 않는다. API DTO·컨트롤러·서비스·기존 테스트·Compose·Jenkins·이벤트 schema를 읽어 설계했다. 현재 G1/G2/G3 실행 및 런타임 동작은 미확인이다.

이번 정상 흐름 설계 작업에서도 `scripts/verify-service-architecture.py` 기본·`--ci`·`--performance` 정적 검사 3종이 PASS였다. 컨테이너·DB·업무 API·Gradle 테스트를 실행하지 않았다. 이는 기존 Compose 계약의 검사 결과이며 아직 구현되지 않은 임시 override나 NF 시나리오의 검증 결과가 아니다.

### 7.3 Claude 독립 검토 및 반영

Herdr의 같은 작업 폴더 `w5:p2` Claude에게 새 문서의 G1~G3에 한정한 읽기 전용 독립 검토를 맡기고 완료 응답을 받았다. Claude는 **차단 결함 없음, FLOW 20→17→15와 원장 계산 및 계약상 기대 응답 일치**로 평가하고 다음 5개 의견을 제시했다.

| 검토 ID / 의견 | Codex 판단·반영 | 위치 |
|---|---|---|
| NR-01 / 중: kid·프로젝트명·이미지 태그 주입 명시 | 채택. kid 일치는 자체 점검 중 이미 추가했고, runId 형식·필수 환경값·실제 개인키 경로와 전송 파일 대조를 보강 | §2.1 |
| NR-02 / 중: 독립 migration 검증은 새 테스트 구현 전제 | 부분 채택. 기존 G1과 NF-13 결과를 분리하고 후속 테스트 보완 의존성을 명시. 현재는 문서만 승인되었으므로 실행 완료를 주장하지 않음. 단순 SQL 적용 후 JAR 기동이라는 대안은 Flyway 원본 이력 생성 절차가 빠져 채택하지 않음 | S1·NF-13·§5·§7.1 |
| NR-03 / 중: SKU 대문자 정규화·계정별 유일성 | 채택. 대문자 fixture, 정규화 후 비교, A 대소문자 중복409/B 동일 SKU201을 명시 | §3.1·NF-05 |
| NR-04 / 낮~중: Outbox에 account_id 컬럼 없음 | 채택. event_key/aggregate_id/event_id 및 published_at 조건을 실제 코드에 맞게 명시 | §5 |
| NR-05 / 낮: GET login 405 증거 범위 한정 | 채택. 코드상 기대와 런타임 미확인, 라우트 도달과 인증/업무 준비 판정을 구분. 401/404의 근본 원인은 추가 로그로 진단 | §2.3 |

일부 의견은 검토 시작 때 읽은 초안을 기준으로 하므로 이미 보완한 항목과 새 반영을 위 표에서 구분했다. 이 기록은 Codex가 원본 근거를 확인해 의견을 반영한 결과이며, 반영본 전체의 Claude 재승인이나 런타임 검증 통과를 뜻하지 않는다.

최종 Annotate 대상은 NF-DEC-01~04, §3의 업무 여정, §4의 시나리오와 §7.1의 완료 조건이다. 검토 후 구현·실행은 사용자의 별도 요청으로 진행한다.
