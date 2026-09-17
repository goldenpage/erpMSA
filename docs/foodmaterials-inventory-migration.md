# FoodMaterialsService 식자재 재고 이관

2026-09-17 사용자 지정에 따라 식자재 재고의 소유 서비스는 FoodMaterialsService다.
설계도의 서비스명·포트 7073·기본 경로 `/foodmaterials`와 7개 업무 서비스 구조를 유지한다.
기존 Inventory 구현은 Git의 `cf2e218^`에서 복구해 FoodMaterials 내부 `inventory` 패키지에 이관했다.
독립 InventoryService 폴더·서버·Eureka 등록·Compose 서비스는 추가하지 않는다.

## 이관 범위

현재고 생성·조회·목록, 수량 조정, 변경 원장, 계정 경계, 낙관적 잠금, 요청 ID 중복 방지,
재고 부족/수량 범위 검사와 재고·원장 원자적 저장을 복구했다.
품목 소유권 확인은 HTTP/Eureka 호출을 없애고 같은 애플리케이션의 카탈로그 서비스에서 수행한다.
품목 하드 삭제나 소유권 이전 API는 현재 없으며 비활성화는 데이터 삭제가 아니다.
Audit 소비자 복구, Purchase·Disposals와의 업무 연동, 단위·유통기한·레시피는 이번 범위에 포함하지 않는다.

## API

| 메서드 | 경로 | 기능 |
|---|---|---|
| POST | `/foodmaterials/inventories` | `foodMaterialId`, `initialQuantity`로 재고 생성 |
| GET | `/foodmaterials/inventories?page=0&size=20` | 로그인 계정의 재고 목록 |
| GET | `/foodmaterials/inventories/{foodMaterialId}` | 현재고·version 조회 |
| POST | `/foodmaterials/inventories/{foodMaterialId}/adjustments` | `requestId`, `quantityDelta`, `version`, `reason`으로 조정 |
| GET | `/foodmaterials/inventories/{foodMaterialId}/movements` | 변경 원장 페이지 조회 |

모든 요청은 JWT Access Token이 필요하다. 생성 응답 Location도 새 경로를 사용한다.
기존 클라이언트는 `/inventories`를 새 경로로, JSON `itemId`를 `foodMaterialId`로 변경해야 한다.
DB 컬럼 `item_id`와 숫자 식별자, 기존 inventory/stock_movement 테이블은 변경하지 않는다.
Gateway의 기존 `/foodmaterials/**` 라우트가 재고 API도 전달한다.

## DB와 트랜잭션

DB 복사·병합, 새 재고 테이블, 기존 재고 DB 연결을 비교했다. 데이터 복사와 이력 충돌을 피하도록
기존 inventorydb를 두 번째 연결로 사용하는 방식을 선택했다. itemdb도 기존 연결을 유지한다.
[Spring Boot 공식 다중 DB 안내](https://docs.spring.io/spring-boot/how-to/data-access.html)에 따라
재고 전용 EntityManagerFactory·Repository 범위·TransactionManager를 분리했다.
`defaultCandidate=false`로 기존 카탈로그 자동 구성을 유지하고 재고 빈은 이름으로 지정한다.

- 카탈로그: 기존 `spring.datasource`, `db/migration`의 V1/V2.
- 재고: `app.inventory.datasource`, `db/inventory-migration`의 기존 V1 SQL 원본.
- 각 DB는 기존 이름의 `flyway_schema_history`를 독립적으로 사용한다. 재고 Flyway 완료 후 재고 JPA를 시작한다.
- Hibernate는 validate, 재고 Flyway clean은 금지한다. 기존 SQL 및 데이터 변경/삭제 명령을 실제 DB에 실행하지 않았다.
- 수량과 원장은 같은 재고 DB 트랜잭션에 포함된다. 카탈로그 조회와 재고 쓰기의 분산 트랜잭션을 보장하는 구성은 아니다.
- 재고 목록·원장은 같은 시각의 페이지 순서를 안정화하도록 ID를 추가 정렬 기준으로 사용한다.
- 재고 연결 풀 이름은 FoodMaterialsInventoryPool, 기본 최대 크기는 10이다. 인스턴스 증설 시 두 풀의 총 DB 연결 수를 고려한다.

## 기존 환경 적용

기존 재고 DB 주소·사용자·비밀번호를 `FOOD_MATERIAL_INVENTORY_DB_URL/USERNAME/PASSWORD`로 옮긴다.
변수 생략으로 빈 다른 DB를 가리키지 않도록 배포 환경의 실제 연결 대상을 확인한다.
기본 Compose는 이전과 같은 MariaDB의 inventorydb를 사용하며 새 환경에서는 스키마를 생성하고 권한을 부여한다.
기존 데이터와 Flyway 이력이 있는 DB는 그대로 연결한다. 이력 없는 기존 DB에는 임의로 baseline을 켜지 않는다.
신규 경로와 JSON 필드로 호출자를 변경하고 이전 Inventory 프로세스를 종료한 뒤 단일 소유자로 전환한다.
DB 백업·기존 수량/원장 대조·배포 후 호출 검증은 실제 환경 전환 시 수행해야 한다.
이번 작업에서 실제 환경 재배포, 기존 DB 변경, 원격 Jenkins 실행은 수행하지 않았다.

## 검증 및 개선

FoodMaterials 전체 단위·통합 테스트 33개가 MariaDB Testcontainers의 임시 DB에서 통과했다.
빈 DB 최초 기동과 기존 V1 이력·재고·원장이 있는 DB 기동을 구분한다.
핵심 검사는 실제 카탈로그 소유권 확인, 10개 동시 요청 중 성공 1/충돌 9,
원장 INSERT 강제 실패 시 수량·버전 롤백, 기존 식별자·수량·버전·원장·Flyway 이력 보존이다.
카탈로그 DB에 재고 테이블이, 재고 DB에 카탈로그 테이블이 잘못 생성되지 않는지도 검사한다.

개선 후보는 데이터 이력 호환성 검사, 실패·동시성 회귀 검사, API/환경변수 전환 안내다.
데이터 보존을 우선으로 기존 데이터 기동 검사를 추가하고, 나머지 두 항목도 테스트와 문서에 반영했다.
Jenkins와 격리 실험 smoke는 Gateway의 새 재고 경로로 생성·조정·원장을 검증하도록 갱신했다.
해당 실제 Gateway smoke와 원격 CI는 이번 로컬 테스트 결과에 포함하지 않는다.

기본·CI·실험 Compose 구조 검사와 실험 볼륨 보호 검사 3개, Jenkins shell 블록 15개의 구문 검사가 통과했다.
[검증 요약 JSON](foodmaterials-inventory-verification.json)에 테스트별 개수와 기존 migration SHA-256을 기록했다.
