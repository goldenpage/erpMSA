# 설계도 기준 서비스 전환 결과

2026-09-15 기준, 문서의 이름뿐 아니라 프로젝트 폴더·Java 패키지/Application·포트·Gateway 경로·Eureka·Docker·CI·관측 설정을 변경했다.
서비스 목록과 업무 완성 범위는 [설계 기준](service-architecture.md)을 따른다. 검증 원본 요약은 [검증 JSON](service-transition-verification.json)이다.

## 변경

- 기존 ItemService를 FoodMaterialsService로 이관하고 `/foodmaterials`, `foodMaterialId`, `foodMaterials` 응답으로 변경했다.
- MenusService, NoticesService, BillsService, PurchaseService, DisposalsService를 독립 실행 프로젝트로 추가했다.
- 신규 5개 서비스는 공통 JWT 검증, Eureka 등록, health/Prometheus를 갖춘 실행 기반이다. 업무 기능은 501이며 완성된 CRUD로 표현하지 않는다.
- Account는 7071, Menus 7072, FoodMaterials 7073, Notices 7074, Bills 7075, Purchase 7076, Disposals 7077을 사용한다.
- Audit·Inventory는 7080·7081의 내부 지원 서비스로 보존하고 기본 host port 및 Gateway 공개 라우트에서 제외했다.
- 기존 `itemdb.item`, `inventorydb`와 Flyway SQL 이력을 보존했다. 식별자 참조를 끊는 DB/테이블 이름 변경은 하지 않았다.
- Jenkins 테스트 모듈·이미지·경로·Prometheus 대상 11개 검사와 새 서비스의 예상 501 검사를 갱신했다.
- 과거 성능 보고서는 그대로 보존하고, 새 테스트 결과는 별도 `performance/results/service-transition/`에 기록했다.

## 확인한 결과

| 검증 | 결과 |
|---|---|
| FoodMaterials 기존 CRUD·소유권·오류·정렬 테스트 | 16개 통과 |
| Inventory 내부 연결/정합성 테스트 | 21개 통과 |
| Gateway 인증·기동 테스트 | 15개 통과 |
| 신규 5개 서비스 기동·인증·만료·501 계약 | 각 4개, 총 20개 통과 |
| 실험 볼륨 보호 테스트 | 3개 통과 |
| 기본/CI Compose 및 서비스 식별자 검사 | 통과 |
| Docker 이미지 빌드 및 격리 환경 기동 | 통과 |
| Eureka 등록 | 7개 업무 서비스 모두 고유 이름으로 UP |
| Prometheus | Spring 서비스 11개 UP |
| 실제 Gateway 신규 경로 | 인증 없으면 401, 인증 후 501 및 각 서비스명 확인 |
| FoodMaterials → 내부 Inventory | 등록·소유권 확인·현재고 조정 통과 |
| 재고 동시 조정 | 성공 1, 충돌 9, 수량 20→19, 원장 2개 |
| Refresh 회전·로그아웃 | 구토큰 및 로그아웃된 토큰 재사용 401 |
| Kafka 중복/DLT | 중복 eventId 저장 1건, 이번 실행의 잘못된 JSON이 DLT로 이동 |
| 제거한 Gateway 경로 | `/items`, `/orders`, `/inventories`는 정상 토큰에도 404 |
| k6 경로/응답 필드 smoke | 21건, HTTP 오류·요청 누락 0 (성능 비교 목적 아님) |
| 기존 FoodMaterials 저장소 migration | 이전 Item V1/V2 SQL과 바이트 단위 일치 |

서비스 테스트 합계는 72개이며 실험 보호 테스트 3개는 별도다. Account/Audit 전체 테스트를 이번 전환에서 다시 실행한 것으로 합산하지 않았다.
임시 DB에는 6개 계정·2,100개 카탈로그 항목을 생성했으며, 실제 데이터베이스나 기존 업무 볼륨을 초기화하지 않았다.

## 호환성과 한계

클라이언트는 기존 `/items`와 `itemId`/`items` 응답 사용을 변경해야 한다. 내부 Inventory의 요청 필드 `itemId`는 보존했으며,
FoodMaterials가 반환하는 `foodMaterialId` 값을 전달한다. 공개 Gateway로 재고 API를 호출하던 클라이언트도 전환 검토 대상이다.

새 서비스 5개의 메뉴·공지·전표·구매·폐기 업무 기능은 아직 구현되지 않았다. 식자재의 단위/유통기한/레시피와 재고 소유권도
이번 이름·실행 구성 전환으로 확정하지 않았다. 실제 업무 명세를 받아 각 서비스의 pending controller를 대체해야 한다.

원격 Jenkins 실행, 실제 업무 환경 재배포, 기존 DB를 사용한 운영 마이그레이션은 하지 않았다.
성능 개선 수치를 새로 주장하지 않으며, 이전 스프린트의 Item/Inventory 측정값을 이름만 바꾸어 인용하지 않는다.

검증 종료 후 임시 컨테이너·네트워크·전용 볼륨을 정리하고 기존 ERP 볼륨이 보존됐음을 확인했다.
