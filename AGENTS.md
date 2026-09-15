# ErpMSA 작업 기준

- 한국어로 작업한다.
- 서비스 구조는 사용자가 제공한 설계도를 반영한 `docs/service-architecture.md`와 `architecture/services.json`을 따른다.
- 목표 업무 서비스는 Account, Menus, FoodMaterials, Notices, Bills, Purchase, Disposals의 7개다. 명칭·포트·경로를 임의로 변경하지 않는다.
- ItemService는 FoodMaterialsService로 이관되었다. Audit(7080)·Inventory(7081)는 별도 내부 지원 서비스이며 Menus/Notices의 대체 서비스가 아니다.
- FoodMaterials의 기초 카탈로그를 전체 식자재 기능으로 과장하지 않는다. Inventory를 Notices로, Audit를 Menus로 치환하지 않는다. 신규 5개 서비스의 업무 API는 아직 501이다.
- OrderService는 목표 설계에 없다. 새 사용자 요청 없이 도입하지 않는다.
- 미구현 서비스의 세부 기능·ERD·업무 이벤트를 서비스 이름만으로 추정해서 확정하지 않는다.
- 실제 전환 시 코드·DB migration·Gateway·Eureka·Compose·환경변수·관측·CI를 함께 점검한다. 업무 포트 7071~7077을 내부 지원 서비스에 재할당하지 않는다. scripts/verify-service-architecture.py를 실행한다.
- 기존 스프린트의 Item/Inventory 측정값을 새 서비스의 실적으로 이름만 바꾸어 기록하지 않는다.
- 실제 DB나 기존 볼륨을 임의로 초기화하지 않는다. 부하·장애 실험은 분리된 프로젝트와 임시 데이터로 수행한다.
