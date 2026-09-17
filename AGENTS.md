# ErpMSA 작업 기준

- 한국어로 작업한다.
- 서비스 구조는 사용자가 제공한 설계도를 반영한 `docs/service-architecture.md`와 `architecture/services.json`을 따른다.
- 목표 업무 서비스는 Account, Menus, FoodMaterials, Notices, Bills, Purchase, Disposals의 7개다. 명칭·포트·경로를 임의로 변경하지 않는다.
- ItemService는 FoodMaterialsService로 이관되었다. AuditService·InventoryService는 사용자 요청에 따라 제거했다. 내부 지원 서비스라는 예외로 다시 추가하지 않는다.
- 식자재 재고는 FoodMaterialsService가 소유한다. 현재고·수량 조정·원장은 내부 inventory 모듈과 기존 inventorydb를 사용하며 별도 InventoryService 서버를 만들지 않는다.
- FoodMaterials의 카탈로그·재고 구현을 전체 식자재 기능으로 과장하지 않는다. Inventory를 Notices로, Audit를 Menus로 치환하지 않는다. MenusService는 기본 음식 메뉴 CRUD·비활성화를, DisposalsService는 폐기 기록과 FoodMaterials 재고 차감을 담당한다. Notices·Bills·Purchase는 아직 501이며 Bills·Purchase는 사용자 지시로 대기한다.
- OrderService는 목표 설계에 없다. 새 사용자 요청 없이 도입하지 않는다.
- 미구현 서비스의 세부 기능·ERD·업무 이벤트를 서비스 이름만으로 추정해서 확정하지 않는다.
- 실제 전환 시 코드·DB migration·Gateway·Eureka·Compose·환경변수·관측·CI를 함께 점검한다. 설계도에 없는 업무 서비스 폴더·실행 구성을 추가하지 않는다. scripts/verify-service-architecture.py를 실행한다.
- 기존 스프린트의 Item/Inventory 측정값을 새 서비스의 실적으로 이름만 바꾸어 기록하지 않는다.
- 실제 DB나 기존 볼륨을 임의로 초기화하지 않는다. 부하·장애 실험은 분리된 프로젝트와 임시 데이터로 수행한다.

- 폐기 재시도는 같은 requestId/폐기 식별자로 처리하며 재고를 중복 차감하지 않는다. 통신 결과가 불명확하면 PENDING(202)으로 유지한다. 폐기 완료·거절과 재고 결과를 임의로 성공 처리하지 않는다.
