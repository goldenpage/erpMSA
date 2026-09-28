# ErpMSA 통합 검증 계획

> 후속 진행(2026-09-28): 격리 환경·G1 구현 및 실행은 [G1 실행 기록](g1-verification-results.md)에 별도로 기록한다. 이 문서의 설계 당시 미실행 기록과 구분하며, G3/G4·원격 CI·운영 검증 완료를 뜻하지 않는다.

> G2 후속: [실제 3서비스 검증 기록](g2-verification-results.md)에 구현·실행 및 발견 결함을 기록했다. 발견한 입력 오류 응답 결함을 구현·수정했고, 수정 후 G1 119개와 G2 10개 시나리오가 모두 PASS다. G3/G4는 미실행이다.

> 설계 기준: v1 · Claude 독립 검토 의견 반영 완료 · Annotate 검토 가능. 현재 구현·실행 상태는 위 후속 기록 참조.
> 작성일: 2026-09-21 · 설계: Codex · 독립 검토: 같은 Herdr 작업 폴더의 Claude
> 기준: `feat/status` / `d11461b52a0e2cb90521b3217d55f960d4c0676e`
> 작업 경로: `/Users/jonghwan/.herdr/worktrees/ErpMSA/feat-status`

## 1. 검토할 결정

7개 업무 서비스의 현재 계약을 대상으로 **인증 → Gateway/Eureka → 업무 처리 → DB 상태**를 연결해 검증한다. 가장 중요한 판정은 폐기 재시도에서 재고가 한 번만 차감되는지, 결과가 불명확할 때 PENDING이 보존되는지다.

이 본문은 최초 설계 범위와 당시 미실행 상태를 보존한다. 이후 사용자의 구현 요청에 따라 G1/G2 실행기·회귀 테스트·발견 제품 결함 수정을 진행했다. G3/G4·원격 CI·운영 검증의 완료 여부는 이 설계 자체로 판정하지 않는다.

G1~G3의 다음 검토 대상은 [정상 흐름 검증 상세 설계](normal-flow-verification-design.md)다. 실행별 단계 자원명, 요청 데이터, 업무 여정과 단계별 판정은 해당 문서에 구체화하며 G4는 이 상위 계획의 후속 범위로 유지한다.

Annotate에서는 아래 결정 ID나 시나리오 ID가 포함된 문단을 선택해 의견을 남긴다.

| 결정 ID | 제안 | 검토할 내용 |
|---|---|---|
| DEC-01 | 정적 검사 → 서비스별 테스트 → 3서비스 직접 HTTP → 7서비스 Gateway → 장애 복구 순서 | 필수 검증 범위가 적절한가 |
| DEC-02 | 폐기 멱등성·계정 경계·불확실한 결과 보존을 최우선 차단 기준으로 지정 | 위험 우선순위에 동의하는가 |
| DEC-03 | 매 실행 전용 임시 자원 사용, 기존 고정 이름 성능 실험실 자동 재사용 금지 | 자원 격리 방식에 동의하는가 |
| DEC-04 | 필수 시나리오의 미실행·SKIP·증거 누락은 완료로 집계하지 않음 | 완료 조건이 적절한가 |
| DEC-05 | 로컬 결과와 원격 Jenkins 결과를 별도 상태로 보고 | CI 검증을 요청할 시점을 별도 결정할 것인가 |

## 2. 확인한 범위와 근거

### 2.1 서비스 계약

기준은 [AGENTS.md](../AGENTS.md), [services.json](../architecture/services.json), [서비스 구조](service-architecture.md)다. 표의 포트는 계약상 서비스 포트이며 직접 JAR 실험의 임시 호스트 포트와 구별한다.

| 서비스 | 포트 / 기본 경로 | 검증할 현재 기능 |
|---|---|---|
| Account | 7071 / `/account` | 가입·로그인·Access JWT·Refresh 회전·로그아웃·Outbox 발행 |
| Menus | 7072 / `/menus` | 메뉴 CRUD·INACTIVE 전환·계정 경계·version 충돌 |
| FoodMaterials | 7073 / `/foodmaterials` | 카탈로그·내부 재고 모듈·조정·원장·멱등 폐기 차감 |
| Notices | 7074 / `/notices` | 인증·발견·명시적 501 계약 |
| Bills | 7075 / `/bills` | 인증·발견·명시적 501 계약, 업무 구현 대기 |
| Purchase | 7076 / `/purchase` | 인증·발견·명시적 501 계약, 업무 구현 대기 |
| Disposals | 7077 / `/disposals` | 폐기 기록·상태 조회·인증된 재시도 |

Gateway는 7070, Eureka는 8761이다. InventoryService·AuditService·OrderService를 추가하지 않는다. FoodMaterials의 재고 DB는 `inventorydb`, 카탈로그는 기존 `itemdb`를 유지한다. 계정은 `mydb`, 메뉴는 `menusdb`, 폐기는 `disposalsdb`다. 기존 데이터·migration 이름을 변경하지 않는다.

레시피·메뉴 판매에 따른 차감·유통기한·구매 입고·청구·폐기 취소/승인, 감사 소비자·DLT 복구, 운영 SLO·다중 호스트 HA는 제외한다. Account Outbox 생산자만 검증하며 현재 없는 업무 소비자의 처리 완료를 요구하지 않는다.

### 2.2 현재 검증 자산과 한계

아래는 파일을 읽어 확인한 범위이며 이번 실행의 테스트 통과 결과가 아니다.

| 근거 파일 | 재사용할 부분 | 추가로 필요한 증거 |
|---|---|---|
| [아키텍처 검사기](../scripts/verify-service-architecture.py) | 7개 폴더·Compose·경로·키 마운트·9개 Spring 관측 대상 | 실행 중 Eureka 등록 및 실제 라우팅 |
| [메뉴 테스트](../MenusService/src/test/java/com/oopsw/menusservice/MenusServiceApplicationTests.java) | MariaDB 기반 CRUD·낙관적 충돌·계정 경계 | Gateway 경유 동일 계약 |
| [폐기 테스트](../DisposalsService/src/test/java/com/oopsw/disposalsservice/DisposalsServiceApplicationTests.java) | 응답 유실·중복·동시 재시도 | 재고 서버는 모의 HTTP 서버. 실제 재고 DB 커밋과 두 DB의 결과 대조 필요 |
| [StockClient 설정 테스트](../DisposalsService/src/test/java/com/oopsw/disposalsservice/disposal/StockClientConfigurationTests.java) | 인프라 호출과 발견 기반 재고 호출의 클라이언트 분리 | 실제 Eureka 등록·발견 후 연동 |
| [3서비스 검증기](../scripts/verify-menu-disposal-flow.py) | 실제 JAR·임시 MariaDB·8개 동일 요청·20→17·원장 1개 | 임시 서명 JWT·discovery 비활성화. Account/Gateway/Eureka 검증 아님. 장애 주입과 로그 보존 보완 필요 |
| [기존 전체 경로 smoke](../performance/smoke.py) | 인증·경로·일반 조정 경합·메뉴·폐기 재전송 | 고정 실험실 및 `results/users.json` seed 의존. 독립 fixture와 실패 증거 수집 필요 |
| [Jenkinsfile](../Jenkinsfile) | 테스트·이미지·관측·인증/업무 smoke | 원격 실행 미확인. Kafka 검사는 Outbox 행 수 중심이며 실제 record 계약 대조 필요 |
| [재고 migration 테스트](../FoodMaterialsService/src/test/java/com/oopsw/foodmaterialsservice/inventory/InventoryMigrationCompatibilityTest.java) | 임시 DB의 V1 이력·수량·version·원장 보존 | 독립된 과거 SQL 기준과의 checksum 대조 및 카탈로그 보존 fixture 보완 |
| [성능 실험실](../performance/lab.py), [실험 Compose](../compose.performance.yaml) | tmpfs·실험 자원 검사 아이디어 | 프로젝트명·포트·일부 볼륨 이름이 고정되어 다른 실행과 충돌 가능 |

설정 파일의 선언과 실제 실행 상태는 별개다. `services.json`의 `pending-runtime-verification`도 이번 작업에서는 수정하지 않는다. 과거 스프린트의 테스트 수·성능 수치를 현재 브랜치 결과로 재사용하지 않는다.

## 3. 검증 환경과 실행 단계

### 3.1 DEC-03: 자원 격리

구현 시 실행 식별자 `runId`를 생성하고 소스 SHA·이미지 식별자·시나리오별 데이터 ID와 연결한다. 전용 환경 생성기는 향후 구현 대상이다.

- 전체 경로 검증은 `erpmsa-it-<runId>` 전용 Compose 프로젝트, 전용 네트워크, MariaDB/Redis/Kafka tmpfs, 실행별 키 및 모니터링 볼륨을 사용한다. 기존 `compose.ci.yaml`의 격리 규칙을 참고하되 Jenkins의 `.env` 덮어쓰기 단계를 로컬에 복사하지 않는다.
- 실제 서비스 포트는 유지하고 호스트 공개는 loopback 임시 포트로 제한한다. 직접 JAR 단계만 기존 검증기의 임시 서비스 포트 방식을 사용한다.
- 기존 `.env`, 실제 DB 주소·자격증명, 전역 JVM/Spring override를 상속하지 않는다. 실행 전용 임시 env/Compose override는 별도 구현 요청 후 생성한다. 현재 설정 파일은 수정하지 않는다.
- Compose 프로젝트명만 바꿔서는 명시적 전역 볼륨 이름이 격리되지 않는다. 기동 전 렌더된 설정에서 모든 볼륨·키 경로·포트·이미지 이름을 검사하고, 기동 후 DB의 프로젝트 label·tmpfs·접속 대상을 확인한다. 불일치면 fixture나 장애 주입 전에 중단한다.
- CI override를 참고할 때 `CI_PROJECT_NAME=erpmsa-it-<runId>`도 명시한다. 선언되거나 마운트되는 모든 named volume은 정확히 `erpmsa-it-<runId>-` 접두사를 가져야 하며 `external` 볼륨을 허용하지 않는다. 기본값 `erpmsa-ci-*`와 기존 ERP/실험실 볼륨이 하나라도 남으면 기동하지 않는다. 공개 포트가 제거된 CI 설정에는 전용 loopback 포트 override가 별도로 필요하다.
- 기존 `erpmsa-sprint4-lab`을 자동 정리하거나 사용하지 않는다. 테스트 자원의 생성 목록을 기록하고 자신이 만든 자원만 정리한다. 기존 볼륨 초기화, 일반 프로젝트의 `down -v`, 공유 이미지 삭제를 금지한다.
- 테스트 종료 전 익명화한 증거를 수집한다. 정상/실패/중단 시 모두 정리를 시도하고 실패하면 남은 자원 ID를 보고한다. 기존 Jenkins 컨테이너의 네트워크를 변경하지 않는다.

### 3.2 단계별 완료 조건

| 단계 | 입력 / 방식 | 완료 조건 | 현재 준비 상태 |
|---|---|---|---|
| G0 정적 계약 | 기준 SHA, 기존 아키텍처 검사기 기본·CI·performance | 3종 모두 PASS, 서비스/키/경로 계약 일치 | 이번 문서 작업에서 PASS |
| G1 서비스별 회귀 | 9개 Spring 프로젝트의 Gradle wrapper, Java 21, 전용 Testcontainers | 테스트 결과 XML에서 실패 0, 필수 테스트 누락·SKIP 0 | 기존 테스트 존재, 이번에는 미실행 |
| G2 실제 3서비스 | FoodMaterials·Menus·Disposals의 해당 SHA bootJar 및 임시 DB | 메뉴·계정 경계·동시 폐기·원장 대조 | 기존 검증기 존재, 보완 필요 |
| G3 전체 경로 | 7개 업무 서비스+Gateway/Eureka, 실제 Account 발행 토큰 | 인증/발견/DB/업무/501/Outbox/관측 필수 사례 PASS | 기존 CI/smoke 일부 재사용, 전용 실행기 필요 |
| G4 장애·복구 | G3 정상 상태와 테스트 전용 장애 제어기 | 응답 유실·서비스 재시작·동시 재시도 후 불변식 유지 | 결정적 장애 주입 구현 필요 |
| G5 보고·정리 | 시나리오별 결과·로그·DB 대조·자원 목록 | 미실행 포함 결과표 생성, 비밀값 미포함, 전용 자원 정리 | 보고 수집기 보완 필요 |

G1은 `eurekaServer`, `gatewayServer`, `AccountService`, `MenusService`, `FoodMaterialsService`, `NoticesService`, `BillsService`, `PurchaseService`, `DisposalsService`를 포함한다. 각 서비스가 사용하는 공유 모듈도 Gradle 의존 관계로 빌드한다. 테스트 종료 코드만으로 통과를 선언하지 않고 XML의 실행·실패·건너뜀 수를 함께 기록한다. Docker/의존성 미확보는 환경 차단으로 보고한다.

리소스 경합을 줄이기 위해 단계와 서비스 빌드는 기본 순차 실행한다. 동시성 시나리오 내부의 요청만 병렬로 보낸다. 구현 시 사용할 버전은 체크아웃의 wrapper/build.gradle 및 이미지 선언을 기준으로 고정하고 이 작업에서 업그레이드하지 않는다.

### 3.3 발견 및 준비 상태

G3 시작 시 인프라 health → DB migration → 개별 애플리케이션 health → Eureka 등록 → Gateway 업무 응답 순서로 확인한다. Eureka에는 7개 업무 서비스의 기대 인스턴스를 대조한다. [Gateway 설정](../gatewayServer/src/main/resources/application.yml)은 `register-with-eureka: false`, `fetch-registry: true`이므로 Gateway 등록을 요구하지 않고 발견한 업무 서비스로 라우팅하는지 확인한다. Eureka 서버도 자기 등록을 하지 않는다. 9개 Spring 모니터링 대상과 Eureka 등록 대상 7개를 구분한다.

토큰 확보 전에는 공개 Account 라우트의 준비 상태를 먼저 확인한다. 기존 smoke처럼 `GET /account/auth/login`의 405로 Account 라우트 도달을 확인하고, 전용 준비 확인 계정을 한 번 가입·로그인한 뒤 아래 인증 경로를 검사한다. 준비 계정 생성은 승인 후 실행할 fixture 단계이며 업무 사례의 A·B 계정과 분리한다. 가입 응답이 유실되면 반복 가입하지 않고 같은 합성 식별자로 생성 여부를 확인한다.

유효한 계정 토큰으로 `/account/auth/me`, `/menus`, `/foodmaterials`, `/disposals`의 200과 미구현 세 경로의 501을 확인한다. 미구현 경로는 `code=ENDPOINT_NOT_IMPLEMENTED`와 해당 `service`도 검사한다. 준비 계정을 만든 이후의 반복 확인은 조회로 한정해 데이터를 추가하지 않는다.

제안 시간 한도는 기동/발견 180초, 1초 간격으로 모든 경로가 연속 3회 기대 응답이면 준비 완료다. 이 값은 실험 한도이며 운영 SLO가 아니다. 읽기 재시도와 실제 업무 재시도를 분리하고, 한도 초과 시 503·인스턴스 목록·migration·로그를 보존해 환경 실패로 분류한다. 401만으로 라우팅 준비를 증명하지 않는다.

## 4. 필수 시나리오와 판정

P0는 인증/데이터 무결성 차단 항목, P1은 나머지 필수 계약 항목이다. P0·P1 모두 통과해야 해당 단계가 완료된다. 각 사례는 고유한 fixture를 사용하며 다른 시나리오의 잔여 재고나 Outbox 행 수에 의존하지 않는다.

### 4.1 인증·라우팅·메뉴·식자재

| ID / 우선순위 | 절차 | 기대 결과 / 증거 |
|---|---|---|
| AUTH-01 / P0 | 합성 계정 A·B 가입, 로그인, `/account/auth/me`, Refresh 회전, 이전 Refresh 재사용, 로그아웃 후 Refresh 재사용 | 201/200, 계정 일치, 회전된 이전 토큰과 로그아웃된 Refresh는 401, logout 204. 쿠키 속성은 환경 설정과 대조 |
| AUTH-02 / P0 | Gateway와 각 서비스에 토큰 없음·만료·잘못된 서명/issuer/audience·Refresh를 Bearer로 전달 | 보호된 업무 경로 401, DB 변경 없음. 아래 토큰 생성 규칙으로 검사할 조건만 변형; 정상 E2E 토큰은 Account에서 발행 |
| ROUTE-01 / P1 | G3 준비 검사와 유효 토큰으로 `/items`, `/inventories`, `/orders` 호출 | 신규 7개 경로가 해당 서비스로 연결, 기존 3개 경로 404. 인증 필터 응답을 라우트 검증으로 오인하지 않음 |
| SHELL-01 / P1 | Notices·Bills·Purchase 정상/미인증 호출 | 정상 토큰 501+코드+서비스명, 미인증 401. 새 업무 데이터·기능을 요구하지 않음 |
| MENU-01 / P1 | A 메뉴 생성→목록/상세→현재 version 수정→오래된 version 수정→DELETE→상세 | 생성 201, 조회/수정 200, 충돌 409, 비활성화 204/INACTIVE, 물리 행 보존. 상태 필터·페이지 순서도 대조 |
| TENANT-01 / P0 | B로 A의 메뉴/식자재/재고/원장/폐기 조회와 수정·비활성화·폐기 retry 시도. 별도로 B가 A의 식자재 ID로 신규 폐기 POST | 기존 소유 리소스 경로는 404. 교차 계정 신규 폐기는 409/REJECTED·INVENTORY_NOT_FOUND이며 B 소유 거절 행 1개 생성. A 재고·원장은 불변. B 목록에 A 소유 행이 노출되지 않음 |
| FOOD-01 / P1 | 카탈로그 생성·목록·상세·수정·비활성화, 잘못된 입력·중복 SKU·낡은 version | 현재 DTO/오류 계약 대조, `foodMaterialId`·`foodMaterials` 필드 유지. 재고 기능과 카탈로그 완성 범위를 구분 |
| INV-01 / P0 | 초기 재고 20, 조정 -3, 조정 requestId 재전송, 같은 version으로 10개 서로 다른 -1 동시 조정 | 최초 17, 일반 조정 중복 409; 별도 재고 20에서 동시 조정은 1건 200/9건 409, 최종 19. 수량·version·원장 증가 수를 대조 |
| INPUT-01 / P1 | 메뉴 음수 가격/필수 누락, 폐기 수량 0·음수/길이 초과, 페이지 경계 위반 | 현재 입력 검증 계약의 400 및 오류 코드, 재고·폐기 DB 변경 없음 |

Refresh 폐기는 Access Token 즉시 무효화 계약과 다르다. 로그아웃 뒤 기존 Access Token이 즉시 401이어야 한다는 요구를 새로 만들지 않는다. 일반 재고 조정의 중복 409와 폐기 차감의 기존 결과 반환을 서로 바꾸지 않는다.

AUTH-02의 조건별 토큰은 실행기가 소유한 **실행 환경에서 신뢰하는 키와 kid**로 서명하고, 정상 대조 토큰의 기대 응답(업무 조회 200·미구현 경로 501)을 먼저 확인한 뒤 issuer·audience·exp·token_type 중 시험 대상만 변형한다. 잘못된 서명 사례는 정상 kid를 유지하고 다른 키로 서명한다. 미등록 kid는 별도 변형으로 검사한다. 모든 사례가 미등록 kid 하나의 이유로 401이 되는 시험을 피한다. 개인키는 시험 실행기와 Account만 보유하고 검증 서비스에 제공하지 않는다.

[RsaJwtVerifier](../shared/jwt-security/src/main/java/com/oopsw/security/RsaJwtVerifier.java)의 `acceptLeeway(30)`을 반영하여 만료 사례의 exp는 검사 시각보다 최소 60초 과거로 만든다. DISP-09는 같은 신뢰 키로 발행한 **A의 만료 Access fixture**로 401·PENDING 불변을 검사한 다음, 실제 Account 로그인으로 받은 A의 새 Access로 retry한다. 이 사례는 기본 15분 TTL 경과 자체를 시험하는 것은 아니다. 다른 시나리오에 영향을 주는 전역 TTL 단축은 하지 않는다.

### 4.2 폐기: 두 DB의 불변식

근거는 [DisposalStore](../DisposalsService/src/main/java/com/oopsw/disposalsservice/disposal/DisposalStore.java), [RestStockClient](../DisposalsService/src/main/java/com/oopsw/disposalsservice/disposal/RestStockClient.java), [InventoryDisposalService](../FoodMaterialsService/src/main/java/com/oopsw/foodmaterialsservice/inventory/service/InventoryDisposalService.java)다.

각 사례에서 `accountId + requestId`로 폐기 행을 찾고, 고정 `disposalId`에서 `DISPOSAL-{disposalId}` 재고 명령 ID를 얻는다. 재고 원장은 `accountId + commandId`로 조회한다. 초기 원장을 포함한 총행 수만으로 중복 차감 여부를 판정하지 않는다.

- COMPLETED: 폐기 행 1개, 해당 DISPOSAL 원장 1개, movementId·quantityAfter 일치. 격리 fixture 재고는 `초기값 - 성공한 서로 다른 폐기 수량 합`과 일치한다.
- PENDING: 폐기 행과 ID 유지. 재고 미차감 또는 이미 차감된 상태 둘 다 가능하며 성공/실패로 단정하지 않는다. 복구 후 동일 명령으로 결과를 대조한다.
- REJECTED: 해당 요청으로 새로운 차감이 발생하지 않는다. 다른 명령의 이전 원장이 있는 충돌 사례는 원장 전체가 0일 것을 요구하지 않는다.
- 확정된 COMPLETED/REJECTED는 재시도로 바뀌지 않는다. requestId 충돌 409의 오류 응답은 새 REJECTED 폐기 행이 생겼다는 의미가 아니다.

| ID / 우선순위 | 독립 fixture와 절차 | 판정 |
|---|---|---|
| DISP-01 / P0 | 재고 20, 수량 3의 동일 요청을 8개 동시 POST, 완료 후 같은 POST와 retry 재호출 | 모두 동일 disposalId, 최종 200/COMPLETED, 20→17, 폐기 1개·명령 원장 1개 |
| DISP-02 / P0 | 동일 requestId의 수량/식자재/사유를 각각 변경해 POST | 409 REQUEST_CONFLICT, 기존 폐기 내용과 재고·원장 불변 |
| DISP-03 / P0 | 20에서 21 폐기, 재고 미등록 식자재 폐기 | 409/REJECTED, 각각 INSUFFICIENT_STOCK/INVENTORY_NOT_FOUND, 새 차감 없음. 재고를 보충하더라도 기존 확정 요청 retry는 거절 유지 |
| DISP-04 / P0 | FoodMaterials에 도달하기 전에 연결 차단 후 POST, 연결 복구 후 동일 ID retry | 최초 202/PENDING·미차감, 복구 후 COMPLETED·정확히 1회 차감 |
| DISP-05 / P0 | 실제 FoodMaterials 차감 커밋 뒤 응답 폐기/읽기 timeout, 복구 후 동시 retry | 최초 202/PENDING이면서 이미 20→17 가능. 최종 동일 원장 참조로 COMPLETED, 추가 차감 없음 |
| DISP-06 / P0 | 하위 응답을 5xx·깨진 JSON·200이지만 다른 requestId/movementType/식자재/수량·유효하지 않은 movementId/quantityAfter로 제어 | 확인 불가 응답은 202/PENDING. 404/409라도 허용 코드 외에는 확정 거절하지 않음. 각 변형 별도 결과 기록 |
| DISP-07 / P0 | 같은 재고 20에 서로 다른 requestId로 수량 15를 2개 동시 폐기 | 성공 1·재고 부족 거절 1, 최종 5, 음수/중복/원장-수량 불일치 없음 |
| DISP-08 / P0 | 차감 커밋 후 폐기 DB 커밋 전 Disposals 프로세스 종료, 서비스만 재기동한 뒤 조회/retry | 클라이언트 연결 종료/5xx 가능. 저장된 PENDING과 고정 ID가 남고 재시도 후 COMPLETED·원장 1개. 이 구간에서 202 반환을 보장한다고 쓰지 않음 |
| DISP-09 / P0 | PENDING 생성 후 Access 만료, 새 Access로 동일 ID retry; B로 같은 retry 시도 | 만료 토큰은 401·상태 불변, A의 새 토큰만 처리 가능, B는 404. 토큰을 폐기 DB에 저장하지 않음 |
| DISP-10 / P1 | PENDING/COMPLETED/REJECTED를 만든 뒤 목록 필터·페이지·상세 조회 | 소유권·필터·정렬·ID·상태 일치. GET 상세는 HTTP 200이며 업무 상태는 body로 판정 |

### 4.3 장애 주입의 재현 조건

DISP-05는 단순히 FoodMaterials를 먼저 중지하는 것으로 대체할 수 없다. 향후 전용 시험 프로세스가 실제 FoodMaterials로 요청을 전달하고 정상 응답을 받은 뒤, 명령 ID로 재고 DB의 커밋 결과를 확인하고 Disposals에 반환할 응답만 유실시킨다. 요청별 단계 기록으로 차감 전/후를 구별한다.

G4 전환은 G3의 **같은 Compose Disposals 서비스**를 중지하고 테스트 중계용 base URL과 `discovery-enabled=false`를 적용해 교체 기동하는 방식이다. 두 속성은 빈 생성 시 결정되므로 실행 중 환경값만 바꾸지 않는다. G3/G4 인스턴스를 함께 두지 않는다. Eureka에서 이전 인스턴스가 제거되고 DISPOSALSSERVICE의 UP 인스턴스가 정확히 1개인 것과, 해당 요청이 중계에 도달한 것을 확인한 뒤 장애를 주입한다. Disposals의 `restart: "no"`도 렌더 결과로 검사한다. 정상 G3 복원도 같은 서비스의 설정 복원·재기동과 경로 재확인으로 수행한다.

DISP-08은 응답 보류 중 읽기 timeout이 먼저 끝나는 경쟁도 통제해야 한다. 제안하는 장애 제어 순서는 중계가 명령 수신 → 해당 전용 Disposals 프로세스 일시 정지(SIGSTOP) 확인 → 중계가 실제 FoodMaterials에 전달 → 원장 커밋과 이미 저장된 PENDING 확인 → Disposals 강제 종료(SIGKILL)다. 이후 중계를 정상화하고 Disposals만 기동한다. 재고 DB나 MariaDB 컨테이너는 재시작하지 않는다. 시험 단계 기록 없이 sleep이나 정상 종료만으로 커밋 직전 종료를 주장하지 않는다. 일시 정지/종료 제어가 지원되지 않으면 이 사례는 NOT_RUN으로 남긴다.

복구 전 실행 전용 DB의 연결/트랜잭션 목록(`information_schema.INNODB_TRX` 등)을 읽어 종료된 Disposals 연결의 트랜잭션이 해제됐는지 확인하고 그 시간을 기록한다. 강제 종료 뒤 잠금 해제 지연 여부와 DB timeout의 실제 값은 현재 미확인이다. 관측되는 복구 중 5xx는 숨기지 않으며 이것만으로 중복 차감을 단정하지도 않는다. 180초 복구 한도 내 잠금 해제·정상 retry·두 DB 불변식 확인까지 모두 성공해야 PASS다. 한도 초과는 복구 검증 실패이고, 관리자가 트랜잭션을 임의 종료해 통과시키지 않는다.

이 중계는 새 업무 서비스가 아닌 일시적인 테스트 도구이며 정규 Compose나 Eureka 업무 서비스 목록에는 넣지 않는다. 장애 단계에서는 테스트용 직접 URL override로 중계에 연결하므로 정상 discovery 연동을 검증하는 G3와 결과를 분리한다. 테스트 도구·임시 override는 아직 구현하지 않았다. G4 장애 기제가 준비되지 않으면 모의 테스트 통과로 대체하지 않고 해당 사례를 NOT_RUN으로 남긴다.

모든 장애는 실행별 자원 소유권 검사와 복구 경로가 준비된 뒤 시작한다. 하위 HTTP 연결/읽기 제한은 현재 2초/3초지만 행 잠금 대기·Gateway·클라이언트 시간이 추가되므로 전체 응답을 5초 이내라고 보장하지 않는다. 단일 요청의 시험 한도는 15초, 장애 복구/조회 재시도 한도는 180초로 제안한다. 한도 초과·예상 외 상태는 기록 후 실패 처리하며 완료될 때까지 무한 재시도하지 않는다.

DISP-04/05/06의 **장애 중 요청은 한 번에 1개**로 제한한다. DISP-05의 동시 retry는 하위 응답을 정상 복원한 뒤에만 수행한다. 장애 중 다수 요청의 잠금 대기·처리량 측정은 이번 범위에서 제외한다. 실제 잠금 timeout이나 전체 응답 지연을 `요청 수 × 5초`로 확정하지 않는다. DISP-08의 의도된 연결 종료/5xx는 주입 구간의 예상 관측으로 별도 기록하고 정상 업무 요청의 15초 기준과 구분한다.

### 4.4 DB·이벤트·관측

| ID / 우선순위 | 절차 | 판정 / 제한 |
|---|---|---|
| DB-01 / P0 | 완전히 빈 임시 DB에서 해당 서비스 migration; 별도 임시 DB에 기존 카탈로그·재고 V1 이력과 합성 데이터 fixture 후 현 migration | 수량·ID·version·원장·기존 Flyway 이력 보존, 성공한 신규 migration만 추가. 원본 SQL hash는 독립 기준 revision과 대조하고 catalog/inventory 테이블 혼입 없음 |
| EVENT-01 / P1 | 한 시험 계정 등록 후 해당 accountId/eventId의 Outbox와 Kafka record를 유한 대기 후 대조 | Outbox PUBLISHED, 토픽·key=accountId 십진 문자열·payload를 [schema](../contracts/account-registered-v1.schema.json)와 대조. 비밀번호/토큰/개인키/이메일/전화번호 미포함 |
| EVENT-02 / P1 | 전용 Kafka만 중지→계정 등록→해당 eventId의 Outbox 저장·실패한 발행 시도 확인→Kafka 복구 | 장애 중 status=PENDING, attempt_count 증가·next_attempt_at 갱신·last_error 존재, published_at 없음. 복구 후 PUBLISHED 및 같은 eventId의 Kafka record 최소 1건. 소비자/DLT/exactly-once는 검증하지 않음 |
| OBS-01 / P1 | 9개 Spring 대상의 health/Prometheus scrape, API 호출 전후 지표, Grafana datasource/dashboard | 대상 전부 scrape 성공, 실제 수집 지표 존재, Grafana datasource 연결 및 구성 확인. 대시보드 화면 품질은 별도 시각 검증 전까지 미확인 |
| OBS-02 / P1 | EVENT-02와 연계해 Outbox 적체/최고 나이 및 복구 관찰 | 장애 중 적체와 복구 후 감소를 기록. 지표 없음/수집 실패를 0으로 해석하지 않음 |

DB-01의 독립 SQL 기준은 Git revision `788e59d2dfe0be7a42c896b0afc08baa303c834d`의 아래 두 경로로 고정한다. 이번에 Git blob을 읽어 현재 대응 파일과 바이트가 같음을 확인했다. 향후 fixture는 이 기준 blob에서 준비하고 Flyway 이력/checksum·합성 데이터 보존을 실제 임시 DB에서 별도로 검증한다. 현재 파일만으로 V1을 준비해 과거 환경 호환성을 증명하지 않는다.

| 기준 revision 내 경로 | 확인한 SHA-256 |
|---|---|
| `InventoryService/src/main/resources/db/migration/V1__create_inventory_schema.sql` | `b4e0bc37f561c722251d30bd1bb7f7da12037b93c54607cf958639ffa1dc3c7e` |
| `ItemService/src/main/resources/db/migration/V1__create_item_schema.sql` | `bb9d01d0b2f12139e109edcfdef767e67a0c9d665803febbbc956ac343e82878` |

이 경로는 과거 Git blob의 위치이며 제거된 서비스 폴더를 재생성하는 지시가 아니다. 기준 blob을 얻을 수 없는 shallow checkout에서는 DB-01을 BLOCKED로 보고한다. V1 보존 증거와 실제 운영 DB 이력 검증은 구별하며, 실제 DB 복사·초기화·운영 migration 실행은 포함하지 않는다.

Kafka record 확인용 임시 소비 도구는 검증 도구이며 업무 소비자를 복구하는 구현이 아니다. 발행 단위 결과는 실행 fixture로 필터링하고 DB 전체 `PUBLISHED=1` 같은 전역 개수를 요구하지 않는다.

Outbox의 실패 판정은 [AccountOutboxEvent](../AccountService/src/main/java/com/oopsw/accountservice/outbox/AccountOutboxEvent.java)와 [migration](../AccountService/src/main/resources/db/migration/V2__create_account_outbox.sql)의 실제 필드로 한다. 별도의 실패 시각 컬럼은 없으므로 실행기가 관측 시각을 기록한다. 복구 후 `published_at` 설정과 `last_error` 해제도 확인한다. Kafka send 대기 실패를 미전달 확정으로 보지 않고 동일 eventId의 중복 record를 허용한다. 실험 중 재시도 관찰과 복구는 각 180초로 제한하고 실제 next_attempt_at도 증거에 남긴다.

## 5. 증거와 완료 판정

향후 결과 수집기는 실행별 디렉터리에 다음을 기록한다. 현재는 설계만 작성하며 결과 디렉터리나 fixture를 만들지 않는다.

| 증거 | 내용 |
|---|---|
| 실행 manifest | runId, 기준 SHA/dirty 여부, 시작·종료시각, 환경 구분, Java/Gradle/Docker/Compose 버전, 이미지 ID/digest, 자원 목록 |
| 시나리오 결과 | ID, PASS/FAIL/BLOCKED/NOT_RUN, 실제 HTTP/업무 상태, 기대값/실제값, 익명화한 요청 식별자, 소요시간 |
| 데이터 대조 | 해당 accountId/requestId/disposalId/commandId의 폐기 행·원장·수량·version, 전후 비교 |
| 실행 증거 | 테스트 XML, 경로 준비 상태, Eureka 인스턴스, 필요한 서비스 로그, 장애 단계 및 복구 시각 |
| 이벤트·관측 | fixture eventId의 Outbox/Kafka 대조, metric sample·scrape 상태, 증거 수집 실패 여부 |
| 정리 결과 | 생성/제거 자원 ID, 남은 자원과 이유, 정리 실패 여부 |

Authorization·Cookie·JWT·DB 비밀번호·개인키·사용자 개인정보는 보고서에 저장하지 않는다. 임시 토큰 파일은 공유 아티팩트와 분리하고 소유자 전용 권한을 적용한 뒤 제거한다. 로그와 Kafka 샘플도 공개 전에 같은 기준으로 필터링한다.

DEC-04의 완료 조건은 다음과 같다.

1. G0~G5의 필수 사례를 모두 실행하고 P0·P1 실패가 0이다. 미실행·차단·SKIP·증거 누락이 하나라도 있으면 해당 범위는 미완료다.
2. 동시성 사례 DISP-01/05/07, INV-01은 서로 독립된 fixture로 각 3회 반복한다. 하나라도 위반하면 실패이며 재실행 성공으로 실패를 지우지 않는다. 세 번 통과가 모든 경쟁 상태의 부재를 증명하지는 않는다.
3. DB 대조로 중복 차감·음수 재고·소유권 침범·원장 불일치가 없고, 불확실한 결과는 PENDING으로 드러난다.
4. 준비 확인/HTTP/복구 대기에 한도가 있고 실패 증거가 남는다. 필수 증거 또는 정리 결과가 없으면 완료로 표시하지 않는다.
5. 로컬 직접 호출, 로컬 전체 경로, 원격 Jenkins, 배포/운영 결과를 분리한다. 원격 Jenkins는 별도 실행 요청 후 같은 SHA·manifest·테스트/아티팩트로 확인한다. 로컬 통과만으로 원격 CI나 운영 성공을 선언하지 않는다.

## 6. 향후 구현 순서

이 목록은 구현 승인 요청의 범위이며 현재 수행한 변경 목록이 아니다.

1. 실행별 환경·fixture·결과 manifest·정리 소유권 검사를 구현한다. 기존 테스트의 외부 환경 상속과 실패 로그 보존 여부를 점검한다.
2. G1/G2를 실행하고 DB 대조를 보완한 뒤 G3 인증·501·경로·업무·Outbox·관측 검증을 연결한다.
3. G4의 결정적 중계/장애 제어를 구현하고 실제 두 DB의 중간 상태와 복구를 검증한다.
4. 로컬 결과를 먼저 보고한다. 원격 CI 편입이나 Jenkinsfile 변경이 필요하면 그 변경 범위를 별도로 제시한다. 발견된 제품 결함도 파일/원인/수정 범위를 보고하고 별도 요청 전 소스를 고치지 않는다.

## 7. 이번 문서의 검증 및 독립 검토

### 7.1 이번에 확인한 사실

- Herdr 내부 `HERDR_ENV=1`, Codex `w5:p1`와 Claude `w5:p2`가 같은 지정 작업 폴더에 있음을 확인했다.
- 기준 HEAD와 작업 시작 시 clean 상태를 확인하고, 서비스·클라이언트·컨트롤러·DB migration·기존 테스트·Compose·CI·실험 도구를 읽었다.
- `python3 scripts/verify-service-architecture.py`, `--ci`, `--performance` 모두 PASS였다. Compose 설정을 해석하는 정적 검사이며 컨테이너·DB를 기동하지 않는다.
- 과거 기준 revision의 카탈로그·재고 V1 두 SQL과 현재 파일의 바이트 동일성을 확인했다. 런타임 DB migration 통과를 의미하지 않는다.
- 이번에는 Gradle 테스트, HTTP 업무 호출, DB 접근/fixture 작성, 장애 주입, Jenkins 실행을 하지 않았다.

### 7.2 Claude 독립 검토 반영 기록

Herdr `w5:p2`의 Claude에게 읽기 전용 독립 검토를 요청하고 완료 응답을 수신했다. Claude는 코드·계약·기존 테스트·Compose·CI·Git 이력을 대조하고 G0 정적 검사 3종 PASS를 별도로 확인했다. 총평은 **차단 결함 없음, 재현 조건 보완 필요**였다. 아래는 Codex가 원본 근거를 재확인하여 반영한 결과다.

| 검토 ID / 원 의견 | 판단과 반영 내용 | 위치 |
|---|---|---|
| CR-01 / 중: 종료 뒤 잠금 및 자동 재기동 통제 | 조건부 채택. restart=no, 트랜잭션 해제 관측, 복구 한도와 최종 무결성 판정을 추가. 잠금 지연·500이 반드시 발생한다거나 모든 500을 허용한다는 해석은 채택하지 않음 | 4.3 / DISP-08 |
| CR-02 / 중: G3/G4 인스턴스 공존 시 비결정적 라우팅 | 채택. 같은 서비스 교체 기동, 이전 등록 제거·UP 1개·중계 도달 검사를 명시 | 4.3 |
| CR-03 / 중: 인증 변형이 미등록 kid 하나로 실패할 위험 | 채택. 신뢰 키 대조군, 한 조건씩 변형, 30초 leeway, 만료 fixture 및 실제 새 Access 사용을 명시 | AUTH-02 / DISP-09 |
| CR-04 / 중: 교차 계정 신규 폐기의 409/REJECTED 계약 | 채택. 기존 조회/retry의 404와 신규 POST의 409·B 소유 거절 행을 분리해 누락 보완 | TENANT-01 |
| CR-05 / 중: 장애 중 병렬 요청의 잠금 대기 | 범위 명확화 채택. 장애 중 단일 요청, 복구 후 동시 retry. N×5초를 확정 상한으로 사용하지 않음 | 4.3 |
| CR-06 / 낮~중: 과거 SQL 기준 확보 가능 | 채택. 직접 확인한 원본 추가 revision·경로·두 SQL hash를 고정 | DB-01 / 4.4 |
| CR-07 / 낮: Outbox 실패·복구 판정 구체화 | 실제 컬럼으로 보정해 채택. 실패 시각 컬럼을 가정하지 않고 attempt_count/next_attempt_at/last_error/관측 시각 및 최소 1개 record를 사용 | EVENT-02 / OBS-02 |
| CR-08 / 낮: CI 볼륨 이름 기본값 충돌 | 채택. CI_PROJECT_NAME 지정, 모든 named volume의 정확한 실행별 접두사 검사 | DEC-03 / 3.1 |

추가로 Codex가 Gateway의 등록 비활성화, 준비 확인용 토큰 확보 순서, 커밋 경계 시험의 일시 정지/강제 종료 단계를 보완했다. 표는 **독립 검토 수신 후 Codex 반영 기록**이며 반영본 전체의 Claude 재승인이나 통합 테스트 통과를 뜻하지 않는다. 실제 DB timeout·장애 도구의 동작·원격 Jenkins 상태는 여전히 미확인이다.

### 7.3 사용자 검토 상태

**Annotate 검토 대기.** DEC-01~05, 시나리오의 누락·우선순위·기대 결과, 자원 격리와 완료 조건을 검토 대상으로 제시한다. 문서 검토 의견은 설계에 반영하며, 구현은 별도 요청 전까지 시작하지 않는다.
