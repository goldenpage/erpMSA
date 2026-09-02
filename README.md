# ErpMSA

Eureka, Gateway, Account, Audit, Item, Inventory 서비스를 하나의 Git 저장소에서 관리하는 모노레포입니다.
각 서비스는 독립적인 Gradle 프로젝트이며 Docker Compose로 함께 실행하거나 별도로 배포합니다.
Prometheus가 서비스 메트릭을 수집하고 Grafana가 기본 모니터링 대시보드를 제공합니다.

회원가입 이벤트는 `AccountService -> Outbox -> Kafka -> AuditService` 순서로 전달됩니다.
AccountService의 DB 저장과 Outbox 기록은 같은 트랜잭션으로 처리하며,
AuditService는 `eventId`를 기준으로 중복 이벤트를 저장하지 않습니다.

## 설정 및 보안 관리 원칙

- `application.yml` 또는 `application.yaml`에는 비밀정보를 저장하지 않습니다.
- 공통 구조와 안전한 기본값만 Git으로 관리합니다.
- DB 비밀번호, JWT 키, Grafana 관리자 비밀번호는 환경변수로 주입합니다.
- 실제 `.env` 파일은 Git에 올리지 않고 `.env.example`만 공유합니다.
- CI에서는 Jenkins Credentials로 비밀정보를 주입합니다.
- 운영에서는 Vault, AWS Secrets Manager 등 별도의 Secret Manager 사용을 권장합니다.
- Jenkins 콘솔 로그에 비밀번호, 토큰, JWT 키가 출력되지 않도록 관리합니다.
- 비밀정보가 노출되면 로그만 삭제하지 않고 해당 자격증명을 즉시 폐기하거나 교체합니다.

## Docker Compose로 전체 실행

루트에서 예제 파일을 복사합니다.

```bash
cp .env.example .env
```

다음 명령으로 비밀값을 생성한 후 대응하는 `.env` 항목에 입력합니다. 각 항목에는 서로 다른 값을 사용합니다.

```bash
# JWT_SECRET_BASE64
openssl rand -base64 64 | tr -d '\n'

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

## 로컬 접속 주소

- Gateway: `http://127.0.0.1:7070`
- AccountService: `http://127.0.0.1:7071`
- AuditService: `http://127.0.0.1:7072`
- ItemService: `http://127.0.0.1:7073`
- InventoryService: `http://127.0.0.1:7074`
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
- `audit-service:7072/actuator/prometheus`
- `item-service:7073/actuator/prometheus`
- `inventory-service:7074/actuator/prometheus`
- `gateway-server:7070/actuator/prometheus`

Prometheus의 `Status > Target health` 화면에서 여섯 대상이 `UP`인지 확인할 수 있습니다.
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
./AuditService/gradlew -p AuditService bootRun
./ItemService/gradlew -p ItemService bootRun
./InventoryService/gradlew -p InventoryService bootRun
```

## API 오류 응답 계약

AccountService, ItemService, InventoryService와 Gateway가 직접 반환하는 오류는 다음 JSON 구조를 사용합니다.
성공 응답 구조와 기존 API 경로는 변경하지 않습니다.

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

## Item API

ItemService는 로그인 계정별 품목을 관리합니다. 모든 `/items/**` 요청은
`Authorization: Bearer <access-token>` 헤더가 필요하며, Gateway와 ItemService가
각각 토큰을 검증합니다. 다른 계정의 품목은 조회하거나 수정할 수 없습니다.

```text
POST   /items              품목 등록
GET    /items              내 품목 목록(page, size, status)
GET    /items/{itemId}     내 품목 상세
PUT    /items/{itemId}     내 품목 수정
DELETE /items/{itemId}     내 품목 비활성화
```

SKU는 계정 안에서 유일하며 영문, 숫자, `.`, `_`, `-`만 사용할 수 있습니다.
삭제 요청은 주문·재고 이력 연결을 보존하기 위해 행을 제거하지 않고 상태를
`INACTIVE`로 변경합니다. ItemService는 별도 `itemdb` 스키마를 사용하고
Flyway가 시작 시 스키마를 생성·검증합니다.

수정 요청의 `version`에는 조회 응답으로 받은 현재 버전을 전달해야 합니다.
다른 요청이 먼저 수정해 버전이 달라졌다면 `409 ITEM_CONFLICT`를 반환하므로,
최신 값을 다시 조회한 뒤 사용자의 변경을 재적용해야 합니다.

## Inventory API

InventoryService는 로그인 계정과 품목별 현재고 및 모든 수량 변경 원장을
`inventorydb`에 저장합니다. 재고 생성 전에 전달받은 Access Token으로
ItemService를 호출하여 해당 품목이 실제로 존재하고 현재 계정 소유인지 확인합니다.

```text
POST /inventories                         재고 및 초기 원장 생성
GET  /inventories                         내 재고 목록(page, size)
GET  /inventories/{itemId}                품목별 현재고 조회
POST /inventories/{itemId}/adjustments    입고·출고 수량 조정
GET  /inventories/{itemId}/movements      재고 변경 원장 조회
```

수량 조정 요청에는 다음 값이 필요합니다.

- `requestId`: 계정 안에서 유일한 요청 ID입니다. 같은 ID를 다시 사용하면
  `409 ADJUSTMENT_ALREADY_EXISTS`를 반환하여 중복 반영을 막습니다.
- `quantityDelta`: 입고는 양수, 출고는 음수이며 `0`은 허용하지 않습니다.
- `version`: 현재고 조회 응답의 버전입니다. 값이 오래되면
  `409 INVENTORY_CONFLICT`를 반환합니다.
- `reason`: 조정 사유이며 원장에 영구 기록됩니다.

현재고 변경과 `stock_movement` 원장 저장은 같은 DB 트랜잭션으로 처리됩니다.
차감 후 수량이 음수가 되면 `409 INSUFFICIENT_STOCK`를 반환하고 현재고와
원장 모두 변경하지 않습니다. 주문 예약·해제 Kafka 이벤트는 OrderService
도입 단계에서 이 서비스에 연결합니다.

## Kafka 이벤트 흐름 확인

Compose 내부 서비스는 `kafka:9092`, 호스트에서 직접 실행한 애플리케이션은
`127.0.0.1:9094`로 Kafka에 접속합니다. 토픽 목록은 다음 명령으로 확인합니다.

```bash
docker compose exec kafka \
  /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server kafka:9092 \
  --list
```

회원가입 후 Outbox와 감사 로그 상태를 확인합니다.

```bash
docker compose exec mariadb sh -ec \
  'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb \
  --host=127.0.0.1 --user=root \
  --execute="SELECT event_id, status, attempt_count FROM mydb.account_outbox_event; \
  SELECT event_id, event_type, aggregate_id FROM auditdb.audit_event;"'
```

`account_outbox_event.status`가 `PUBLISHED`이고 같은 `event_id`가
`auditdb.audit_event`에 한 번만 존재하면 정상입니다. 처리할 수 없는 이벤트는
`account.lifecycle.v1.DLT` 토픽으로 이동합니다.

기존 로컬 `mydb`에는 Flyway 이력이 없으므로 Compose에서
`FLYWAY_BASELINE_ON_MIGRATE=true`를 사용해 현재 Account 스키마를 V1으로 등록한 뒤
V2 Outbox 마이그레이션만 적용합니다. 새 데이터베이스와 CI에서는 V1부터 실행됩니다.

## 운영 환경 주의사항

- `DB_PASSWORD`, `JWT_SECRET_BASE64`, `GRAFANA_ADMIN_PASSWORD`, `GRAFANA_SECRET_KEY`는 필수입니다.
- 운영에서는 `JPA_DDL_AUTO=validate`, `JPA_SHOW_SQL=false`를 사용합니다.
- HTTPS 환경에서는 `COOKIE_SECURE=true`, `GRAFANA_COOKIE_SECURE=true`를 사용합니다.
- 실제 자격증명을 Git 커밋, Docker 이미지, Jenkins 로그에 포함하지 않습니다.
- Grafana의 기본 SQLite 저장소는 로컬 개발용이며 고가용성 운영 환경에서는 PostgreSQL 또는 MySQL을 사용합니다.
- Prometheus 보존 기간과 볼륨 크기를 운영 트래픽에 맞게 설정합니다.
