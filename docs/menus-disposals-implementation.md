# 음식 메뉴 관리와 식자재 폐기

2026-09-17 사용자 지정 범위는 기본 음식 메뉴 관리와 폐기 기록·재고 차감이다.
서비스명·포트·기본 경로는 설계도를 유지한다. Menus 7072 `/menus`, Disposals 7077 `/disposals`다.
Bills·Purchase는 대기, Notices는 미구현 501 상태다. 감사 소비자 복구는 이번 작업 범위에 포함하지 않는다.

## 메뉴

`POST /menus`는 이름(name), 설명(description, 선택), 가격(price)을 받아 ACTIVE로 생성한다.
`GET /menus`는 계정별 목록을 page·size·status로 조회하며 createdAt·id 내림차순으로 정렬한다.
`GET /menus/{menuId}`, `PUT /menus/{menuId}`, `DELETE /menus/{menuId}`는 상세·수정·비활성화다.
수정은 name·description·price·status·version을 사용하고 오래된 버전은 409로 거절한다.
ACTIVE/INACTIVE는 판매 활성 상태이며 임시 품절·레시피·식자재별 사용량 계산은 포함하지 않는다.
타계정은 상세·수정·비활성화를 할 수 없으며 404를 반환한다. 물리 삭제하지 않는다.

## 폐기와 재고 차감

- `POST /disposals`: requestId(최대 64자), foodMaterialId, quantity(양의 정수), reason(최대 255자).
- `GET /disposals?page=0&size=20&status=PENDING`: 내 폐기 요청 목록과 상태 필터.
- `GET /disposals/{disposalId}`: 내 폐기 요청 상세.
- `POST /disposals/{disposalId}/retry`: 내 PENDING 요청 재시도. 새로운 유효 Access Token을 사용한다.

수량 단위는 기존 재고의 정수 단위를 따른다. 별도 소수 수량·단위 환산을 가정하지 않는다.
같은 계정의 requestId는 동일한 내용을 가진 한 폐기 요청을 뜻한다. 다른 수량·식자재·사유로 재사용하면 409다.
폐기 수정·취소·삭제 API는 제공하지 않는다. 확정 기록을 수정하며 재고를 임의로 되돌리지 않는다.

| HTTP / 상태 | 의미와 후속 처리 |
|---|---|
| 200 COMPLETED | 재고 차감 원장과 폐기 완료 기록을 확인함. movementId·quantityAfter 제공 |
| 202 PENDING | 처리 결과를 확정하지 못함. 성공 또는 실패로 간주하지 말고 같은 요청을 재시도 |
| 409 REJECTED | 재고 없음·부족·요청 충돌 등 확정된 거절. 원인을 해결한 새 요청에는 새 requestId 사용 |

처리 순서는 다음과 같다.

1. Disposals의 disposalsdb에 식자재·수량·사유·requestId·고정 disposalId를 PENDING으로 커밋한다.
2. 해당 요청 행을 잠그고 FoodMaterials에 `DISPOSAL-{disposalId}`를 명령 ID로 전달한다.
3. FoodMaterials는 계정 소유 재고를 잠그고, 같은 명령의 기존 DISPOSAL 원장이 있으면 그 결과를 반환한다.
   내용이 다르면 충돌이며, 새 명령은 수량과 DISPOSAL 원장을 같은 재고 DB 트랜잭션으로 저장한다.
4. Disposals는 확인한 결과만 COMPLETED/REJECTED로 저장한다. 타임아웃·5xx·응답 형식 이상은 PENDING으로 남긴다.

동일 요청의 동시 처리와 뒤늦은 응답이 완료/거절 상태를 덮어쓰지 않도록 Disposals의 행 잠금은
제한된 HTTP 호출까지 포함한다. 연결 제한은 2초, 읽기 제한은 3초다. FoodMaterials의 재고 잠금은 그 내부 트랜잭션 범위다.
재고 DB와 폐기 DB를 한 분산 트랜잭션으로 커밋하는 구성은 아니다. 차감 후 응답 유실 또는 폐기 DB 커밋 실패는
같은 명령 재전송으로 복구한다. 자동 백그라운드 재시도는 없으며 토큰을 DB에 저장하지 않는다.
PENDING 목록을 확인해 인증된 재시도를 수행해야 한다. 재시도를 하지 않으면 PENDING이 자동 완료되지 않는다.

FoodMaterials의 연동 경로는 `POST /foodmaterials/inventories/{foodMaterialId}/disposals`이며
requestId·quantity·reason을 받는다. 사용자 Access Token을 전달받아 계정 소유권을 검증한다.
일반 재고 조정 권한과 같은 계정 경계를 사용하며 별도 서비스 전용 인증 체계를 추가한 것은 아니다.
직접 재고 조정 호출과 Disposals를 통한 업무 요청은 구분해야 한다.

## 선택과 검토

공유 DB의 직접 쓰기, Kafka 기반 비동기 처리, 기록을 먼저 저장하는 동기 HTTP 처리를 비교했다.
현재 요구인 즉시 결과 확인과 기존 사용자 JWT 경계를 고려해 동기 HTTP와 영속 요청·멱등 차감을 선택했다.
두 DB의 중간 상태를 숨기지 않고 PENDING을 계약에 포함했다. 미정 업무 이벤트를 새로 만들지 않았다.
[Spring Data JPA 잠금](https://docs.spring.io/spring-data/jpa/reference/jpa/locking.html)과
[Spring REST 클라이언트](https://docs.spring.io/spring-framework/reference/integration/rest-clients.html)의 공식 문서를 확인했다.

개선 항목은 중복 차감 방지, 실패 후 재시도 검증, 운영자의 대기 요청 식별이다.
가장 위험한 중복 차감을 우선해 원장 멱등성과 동시 요청 잠금을 구현했고,
응답 유실 테스트 및 status=PENDING 조회도 함께 반영했다.

## DB·설정·배포 순서

- Menus: menusdb, MENUS_DB_URL/USERNAME/PASSWORD, Flyway V1.
- Disposals: disposalsdb, DISPOSALS_DB_URL/USERNAME/PASSWORD, Flyway V1.
- FoodMaterials: 기존 inventorydb의 원본 V1은 변경하지 않고 V2로 원장 타입 DISPOSAL을 추가한다.
- 두 서비스에 새 Flyway V1을 추가했으며 실제 DB를 초기화하지 않는다. 배포 대상에 이미 테이블이 있다면 기존 스키마를 먼저 대조하고 임의 baseline을 켜지 않는다.
- 기본 Compose의 database-init에 스키마 생성·권한 설정을 추가했다. CI·실험 구성은 이를 상속한다.
- Disposals는 기본적으로 Eureka의 FOODMATERIALSSERVICE를 호출한다. 직접 호출 실험에서만
  FOOD_MATERIAL_DISCOVERY_ENABLED=false와 전용 FOOD_MATERIAL_SERVICE_BASE_URL을 사용한다.
- 먼저 FoodMaterials의 V2·새 API를 적용하고 메뉴·폐기 서비스를 배포한다. 이전 FoodMaterials만 남아 있으면
  새 폐기 API 호출을 확인할 수 없어 PENDING으로 유지된다. 실제 환경 배포와 원격 Jenkins는 이번 작업에서 실행하지 않았다.

## 검증

Menus 5개, Disposals 6개, FoodMaterials 37개로 총 48개 단위·통합 테스트가 통과했다.
메뉴 생성·조회·수정·비활성화·페이지·계정 경계, 폐기 등록·거절·다른 내용 충돌,
동시 재시도, 차감 후 응답 유실, 식자재 재고 10개 동일 명령의 단일 차감과 롤백을 포함한다.
기존 재고 V1 상태의 DB를 기동해 V2가 적용되고 기존 수량·원장이 유지되는 것도 확인한다.
Disposals 통합 테스트의 FoodMaterials 응답은 제어 가능한 HTTP 서버로 재현한다.

실제 세 서비스 JAR 간 검증은 `scripts/verify-menu-disposal-flow.py`로 수행한다.
전용 이름과 tmpfs를 사용하는 일회용 MariaDB·임시 키·임시 포트로 실행하며 기존 .env·DB·볼륨을 사용하지 않는다.
Gateway·Eureka·Account 발행은 이 검증 범위에 포함하지 않는다. JWT는 임시 실험 키로 서명한다.
Jenkins 및 performance/smoke.py는 실제 Gateway 경로의 메뉴·폐기를 검사하도록 갱신했으나 그 원격 실행 결과로 간주하지 않는다.

실제 JAR 연동 검증도 통과했다. 폐기 요청 8개 동시 전송에서 요청 기록 1개·폐기 원장 1개,
재고 20→17의 단일 차감을 확인했고 재고 부족 요청은 추가 차감 없이 거절됐다.
임시 프로세스·DB 컨테이너·키는 실행 후 정리했다. 결과는 [검증 JSON](menus-disposals-verification.json)에 기록했다.
기본·CI·실험 Compose 검사, 실험 볼륨 보호 3개, Jenkins shell 블록 15개 구문 검사도 통과했다.

로컬 재현은 Java 21·Docker와 세 서비스의 bootJar가 필요하다.

```bash
./MenusService/gradlew -p MenusService bootJar --no-daemon
./DisposalsService/gradlew -p DisposalsService bootJar --no-daemon
./FoodMaterialsService/gradlew -p FoodMaterialsService bootJar --no-daemon
python3 scripts/verify-menu-disposal-flow.py
```
