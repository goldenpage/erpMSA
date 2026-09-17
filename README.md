# ErpMSA

사용자가 제공한 설계도를 기준으로 하는 ERP MSA 모노레포입니다.
서비스 구조의 기준은 [서비스 설계 기준](docs/service-architecture.md)과 [서비스 식별자 계약](architecture/services.json)입니다.

## 목표 서비스와 구현 상태

| 서비스 | 포트 | 기본 경로 | 현재 상태 |
|---|---:|---|---|
| Account Service | 7071 | `/account` | 구현 있음 |
| Menus Service | 7072 | `/menus` | 음식 메뉴 CRUD·비활성화 |
| FoodMaterials Service | 7073 | `/foodmaterials` | 기초 카탈로그 CRUD·현재고·수량 조정·원장 |
| Notices Service | 7074 | `/notices` | 서비스 실행 기반, 업무 API 501 |
| Bills Service | 7075 | `/bills` | 서비스 실행 기반, 업무 API 501 |
| Purchase Service | 7076 | `/purchase` | 서비스 실행 기반, 업무 API 501 |
| Disposals Service | 7077 | `/disposals` | 폐기 기록·식자재 재고 차감·안전한 재시도 |

위 7개 서비스가 실제 독립 Gradle 프로젝트와 Compose 서비스로 구성되어 있습니다.
Menus는 이름·설명·가격·판매 상태를 관리하고 Disposals는 식자재 폐기 기록과 재고 차감을 연결합니다.
Notices·Bills·Purchase는 아직 501을 반환하며 Bills·Purchase는 요청에 따라 대기합니다.
FoodMaterials는 기존 품목 카탈로그와 식자재 재고 기능을 함께 담당합니다. 전체 식자재 업무 기능이 완성된 것은 아닙니다.

설계도 외 AuditService와 InventoryService는 폴더와 실행 구성에서 제거했습니다.
재고 기능은 FoodMaterialsService 내부로 이관했습니다. 감사 저장 소비자는 아직 없습니다. 기존 DB와 데이터 볼륨은 보존합니다.
[기존 환경 전환 절차](docs/service-architecture.md#기존-환경-전환)를 확인하세요.

회원가입 이벤트는 `AccountService -> Outbox -> Kafka`까지 발행합니다.
계정과 Outbox 기록은 같은 DB 트랜잭션으로 저장하며 현재 업무 소비자는 없습니다.

## 설정 및 보안 관리 원칙

- `application.yml` 또는 `application.yaml`에는 비밀정보를 저장하지 않습니다.
- 공통 구조와 안전한 기본값만 Git으로 관리합니다.
- DB 비밀번호와 Grafana 관리자 비밀번호는 환경변수로 주입합니다.
- JWT는 RS256을 사용합니다. AccountService만 개인키 파일을 받으며, Gateway·나머지 업무 서비스는 공개키만 받습니다.
- 실제 `.env` 파일은 Git에 올리지 않고 `.env.example`만 공유합니다.
- CI에서는 Jenkins Credentials로 비밀정보를 주입합니다.
- 운영에서는 Vault, AWS Secrets Manager 등 별도의 Secret Manager 사용을 권장합니다.
- Jenkins 콘솔 로그에 비밀번호, 토큰, JWT 키가 출력되지 않도록 관리합니다.
- 비밀정보가 노출되면 로그만 삭제하지 않고 해당 자격증명을 즉시 폐기하거나 교체합니다.

## Docker Compose로 현재 구현 실행

루트에서 예제 파일을 복사합니다.

```bash
cp .env.example .env
```

JWT 키를 생성합니다. 기존 키를 덮어쓰지 않으며 `secrets/`는 Git과 Docker 빌드 컨텍스트에서 제외합니다.

```bash
./scripts/generate-jwt-keys.sh
```

다음 명령으로 비밀값을 생성한 후 대응하는 `.env` 항목에 입력합니다. 각 항목에는 서로 다른 값을 사용합니다.

```bash
# GRAFANA_ADMIN_PASSWORD
openssl rand -base64 32 | tr -d '\n'

# GRAFANA_SECRET_KEY
openssl rand -hex 32
```

Docker Compose는 루트의 `.env`에서 값을 읽되 각 서비스에 필요한 환경변수만 전달합니다.

```bash
docker compose up -d --build --wait
```

상태와 로그를 확인합니다.

```bash
docker compose ps
docker compose logs -f
```

종료할 때는 데이터 볼륨을 유지합니다.

```bash
docker compose down
```

`docker compose down -v`는 MariaDB, Redis, Kafka, Prometheus, Grafana 데이터를 삭제하므로 초기화가 필요한 경우에만 사용합니다.

## Jenkins 실행 및 이미지 갱신

Jenkins는 기본 Compose와 분리되어 있으므로 별도로 실행합니다. 최초 실행과
`jenkins/Dockerfile` 변경 후에는 이미지를 다시 빌드해야 합니다.

```bash
docker compose -f compose.jenkins.yaml up -d --build --wait
docker compose -f compose.jenkins.yaml ps
```

접속 주소는 `http://127.0.0.1:8080`입니다. 기존 `erpmsa-jenkins-home` 볼륨의 설정과
빌드 이력을 유지합니다. 실행 중인 빌드가 끝난 뒤 이미지를 갱신합니다.
상태 검사는 로그인 페이지 응답과 CI 구조 검증에 필요한 Python 설치 여부를 확인합니다.
`python3: not found`로 빌드가 실패하면 호스트에 Python을 설치하는 대신 위 명령으로
Jenkins 이미지를 갱신합니다.

CI는 체크아웃 전에 작업 폴더를 정리하여 제거된 서비스의 Gradle 산출물이 구조 검증에
섞이지 않게 합니다. 일반 ERP 환경과 Docker Desktop 메모리를 공유하므로 테스트와
서비스 이미지 빌드는 순차 실행합니다.

## 현재 구현의 로컬 접속 주소

- Gateway: `http://127.0.0.1:7070`
- AccountService: `http://127.0.0.1:7071`
- MenusService: `http://127.0.0.1:7072`
- FoodMaterialsService: `http://127.0.0.1:7073`
- NoticesService: `http://127.0.0.1:7074`
- BillsService: `http://127.0.0.1:7075`
- PurchaseService: `http://127.0.0.1:7076`
- DisposalsService: `http://127.0.0.1:7077`
- Eureka: `http://127.0.0.1:8761`
- Prometheus: `http://127.0.0.1:9090`
- Grafana: `http://127.0.0.1:3000`
- MariaDB: `127.0.0.1:3306`
- Redis: `127.0.0.1:3308`
- Kafka: `127.0.0.1:9094`

컨테이너 내부에서는 Docker Compose 서비스 이름과 컨테이너 포트를 사용합니다.

## Prometheus와 Grafana

Prometheus는 15초마다 다음 엔드포인트를 수집합니다.

- `eureka-server:8761/actuator/prometheus`
- `account-service:7071/actuator/prometheus`
- `foodmaterials-service:7073/actuator/prometheus`
- `gateway-server:7070/actuator/prometheus`
- `menus-service:7072/actuator/prometheus`
- `notices-service:7074/actuator/prometheus`
- `bills-service:7075/actuator/prometheus`
- `purchase-service:7076/actuator/prometheus`
- `disposals-service:7077/actuator/prometheus`

Prometheus의 `Status > Target health` 화면에서 9개 Spring 서비스 대상이 `UP`인지 확인할 수 있습니다.
Grafana에는 `ErpMSA/ErpMSA Spring Services` 대시보드가 자동으로 등록됩니다.
Grafana 로그인 정보는 `.env`의 `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`를 사용합니다.

Actuator와 모니터링 포트는 로컬 호스트에만 바인딩됩니다. 운영에서는 인터넷에 직접 공개하지 않고 사설 네트워크, 방화벽, TLS 및 접근 제어를 적용해야 합니다.

## Gradle로 개별 실행

특정 서비스를 IDE나 Gradle로 실행할 때는 먼저 환경변수를 현재 터미널로 내보냅니다.

```bash
set -a
source .env
set +a
```

```bash
./eurekaServer/gradlew -p eurekaServer bootRun
./gatewayServer/gradlew -p gatewayServer bootRun
./AccountService/gradlew -p AccountService bootRun
./FoodMaterialsService/gradlew -p FoodMaterialsService bootRun
./MenusService/gradlew -p MenusService bootRun
./NoticesService/gradlew -p NoticesService bootRun
./BillsService/gradlew -p BillsService bootRun
./PurchaseService/gradlew -p PurchaseService bootRun
./DisposalsService/gradlew -p DisposalsService bootRun
```

## API 오류 응답 계약

AccountService, FoodMaterialsService와 Gateway가 직접 반환하는 오류는 다음 JSON 구조를 사용합니다.
FoodMaterials의 경로와 식별자 필드는 전환에 맞춰 변경되었습니다. 상세 호환성 변경은 설계 기준 문서를 확인하세요.

```json
{
  "timestamp": "2026-08-31T00:00:00Z",
  "status": 400,
  "code": "INVALID_REQUEST",
  "message": "요청 값이 올바르지 않습니다.",
  "path": "/account/auth/register",
  "fieldErrors": [
    {
      "field": "email",
      "message": "올바른 형식의 이메일 주소여야 합니다."
    }
  ]
}
```

- `code`는 클라이언트가 분기 처리할 수 있는 고정된 오류 코드입니다.
- `message`는 사용자에게 표시할 수 있는 안전한 설명입니다.
- `fieldErrors`는 요청 검증 실패일 때만 채우고 그 외에는 빈 배열을 반환합니다.
- 비밀번호, 토큰, 입력값 원문과 내부 예외 메시지는 오류 응답에 포함하지 않습니다.

## FoodMaterials API

FoodMaterialsService는 로그인 계정별 품목을 관리합니다. 모든 `/foodmaterials/**` 요청은
`Authorization: Bearer <access-token>` 헤더가 필요하며, Gateway와 FoodMaterialsService가
각각 토큰을 검증합니다. 다른 계정의 품목은 조회하거나 수정할 수 없습니다.

```text
POST   /foodmaterials              품목 등록
GET    /foodmaterials              내 품목 목록(page, size, status)
GET    /foodmaterials/{foodMaterialId}     내 품목 상세
PUT    /foodmaterials/{foodMaterialId}     내 품목 수정
DELETE /foodmaterials/{foodMaterialId}     내 품목 비활성화
```

SKU는 계정 안에서 유일하며 영문, 숫자, `.`, `_`, `-`만 사용할 수 있습니다.
삭제 요청은 품목 참조 이력을 보존하기 위해 행을 제거하지 않고 상태를
`INACTIVE`로 변경합니다. FoodMaterialsService는 별도 `itemdb` 스키마를 사용하고
Flyway가 시작 시 스키마를 생성·검증합니다.

수정 요청의 `version`에는 조회 응답으로 받은 현재 버전을 전달해야 합니다.
다른 요청이 먼저 수정해 버전이 달라졌다면 `409 FOOD_MATERIAL_CONFLICT`를 반환하므로,
최신 값을 다시 조회한 뒤 사용자의 변경을 재적용해야 합니다.

## 식자재 재고 API

FoodMaterialsService가 기존 `inventorydb`를 별도 DB 연결로 사용합니다.
재고 생성 시 같은 서비스의 카탈로그에서 계정 소유권을 검사하며, 수량과 변경 원장은 한 재고 DB 트랜잭션으로 저장합니다.

```text
POST /foodmaterials/inventories                              재고 생성
GET  /foodmaterials/inventories                              내 재고 목록
GET  /foodmaterials/inventories/{foodMaterialId}             현재고 조회
POST /foodmaterials/inventories/{foodMaterialId}/adjustments 수량 조정
GET  /foodmaterials/inventories/{foodMaterialId}/movements   변경 원장
```

생성 본문은 `foodMaterialId`, `initialQuantity`를 사용합니다. 조정 본문은 `requestId`, `quantityDelta`, `version`, `reason`입니다.
중복 요청·버전 충돌·재고 부족은 409, 타계정 및 없는 식자재는 404로 처리합니다. 모든 경로는 Access Token이 필요합니다.
기존 `/inventories` 경로와 JSON의 `itemId`는 새 경로와 `foodMaterialId`로 변경해야 합니다.
물리 DB의 `item_id`와 기존 데이터·Flyway 이력은 그대로 유지합니다.
[이관 방식과 검증 결과](docs/foodmaterials-inventory-migration.md)를 확인하세요.

## 음식 메뉴 및 폐기 API

메뉴는 `/menus`의 POST·GET과 `/menus/{menuId}`의 GET·PUT·DELETE로 관리합니다.
등록 시 `name`, `description`, `price`, 수정 시 `status`(ACTIVE/INACTIVE)와 `version`을 함께 보냅니다.
DELETE는 비활성화이며 레시피·식자재별 사용량 연결은 아직 구현하지 않습니다.

폐기는 `POST /disposals`에 `requestId`, `foodMaterialId`, `quantity`, `reason`을 보냅니다.
Disposals가 기록을 저장한 뒤 FoodMaterials에 재고 차감을 요청합니다.
완료는 200/COMPLETED, 재고 부족 등 거절은 409/REJECTED, 통신 결과가 불명확하면 202/PENDING입니다.
PENDING은 `POST /disposals/{disposalId}/retry` 또는 같은 requestId·내용의 등록 요청으로 재시도합니다.
`GET /disposals`와 `GET /disposals/{disposalId}`로 내 처리 상태와 이력을 조회합니다.
재시도에도 차감은 한 번만 적용하며, 같은 requestId에 다른 내용을 보내면 409입니다.
[상세 계약과 실패 처리·검증](docs/menus-disposals-implementation.md)을 참고하세요.

## Kafka 이벤트 흐름 확인

Compose 내부 서비스는 `kafka:9092`, 호스트에서 직접 실행한 애플리케이션은
`127.0.0.1:9094`로 Kafka에 접속합니다. 토픽 목록은 다음 명령으로 확인합니다.

```bash
docker compose exec kafka \
  /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server kafka:9092 \
  --list
```

회원가입 후 Outbox의 발행 상태를 확인합니다.

```bash
docker compose exec mariadb sh -ec \
  'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb \
  --host=127.0.0.1 --user=root \
  --execute="SELECT event_id, status, attempt_count FROM mydb.account_outbox_event;"'
```

`account_outbox_event.status`의 `PUBLISHED`는 Kafka 발행 성공을 나타냅니다.
현재 감사 소비자와 DLT 처리 구현은 없으므로 업무 처리 완료를 의미하지 않습니다.

기존 로컬 `mydb`에는 Flyway 이력이 없으므로 Compose에서
`FLYWAY_BASELINE_ON_MIGRATE=true`를 사용해 현재 Account 스키마를 V1으로 등록한 뒤
V2 Outbox 마이그레이션만 적용합니다. 새 데이터베이스와 CI에서는 V1부터 실행됩니다.

## 운영 환경 주의사항

- `DB_PASSWORD`, `GRAFANA_ADMIN_PASSWORD`, `GRAFANA_SECRET_KEY`와 JWT 키 파일은 필수입니다.
- 운영에서는 `JPA_DDL_AUTO=validate`, `JPA_SHOW_SQL=false`를 사용합니다.
- HTTPS 환경에서는 `COOKIE_SECURE=true`, `GRAFANA_COOKIE_SECURE=true`를 사용합니다.
- 실제 자격증명을 Git 커밋, Docker 이미지, Jenkins 로그에 포함하지 않습니다.
- Grafana의 기본 SQLite 저장소는 로컬 개발용이며 고가용성 운영 환경에서는 PostgreSQL 또는 MySQL을 사용합니다.
- Prometheus 보존 기간과 볼륨 크기를 운영 트래픽에 맞게 설정합니다.

## 4차 스프린트: 운영 검증

아래 기록은 전환 전 Account·Item·Inventory·Audit 구성의 실험 이력입니다.
목표 서비스로 전환한 뒤에는 변경된 업무 모델과 API에서 다시 검증해야 합니다.

[설계 선택과 키 교체 절차](docs/sprint4-design.md), [부하·장애 실험 절차](performance/README.md),
[이벤트 계약](contracts/README.md)을 함께 관리합니다. 실험 데이터는 별도 Compose 프로젝트와 임시 DB에 생성합니다.
측정 결과와 한계는 [실험 보고서](docs/sprint4-results.md)에 기록합니다.

HS256 토큰은 RS256 전환 후 사용할 수 없으므로 최초 전환에는 재로그인이 필요합니다.
이후 RS256 키 교체는 새 공개키 선배포 → 서명키 전환 → 기존 토큰 만료 대기 → 구키 제거 순서입니다.
공개키는 시작 시 읽는 스냅샷이므로 파일 교체 후 각 검증 인스턴스를 순차 재시작합니다.
Access와 Refresh의 기본 만료는 각각 15분과 14일입니다. Refresh를 포함한 키 폐기 정책을 적용합니다.

Jenkins는 매 빌드 일회용 RSA 키를 생성합니다. Jenkins 컨테이너의 경로를 호스트에 bind mount하지 않고
전용 공개키·개인키 볼륨에 전달하며, 종료 시 해당 빌드 볼륨을 제거합니다.
개별 서비스 이미지 빌드는 공유 JWT 모듈을 포함하므로 저장소 루트에서
`docker build -f FoodMaterialsService/Dockerfile .`처럼 실행합니다.
