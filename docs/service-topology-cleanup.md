# 설계도 외 서비스 제거

2026-09-17 사용자 요청에 따라 AuditService와 InventoryService를 내부 지원 서비스로 남겼던 결정을 철회했다.
폴더·소스·빌드 설정을 제거하고 업무 서비스를 설계도의 7개로 맞췄다.

- AccountService: 7071 `/account`
- MenusService: 7072 `/menus`
- FoodMaterialsService: 7073 `/foodmaterials`
- NoticesService: 7074 `/notices`
- BillsService: 7075 `/bills`
- PurchaseService: 7076 `/purchase`
- DisposalsService: 7077 `/disposals`

Gateway와 Eureka는 기존 인프라로 유지한다. 신규 5개 서비스의 업무 API는 여전히 501이다.

## 영향과 연계 수정

- Compose 기본·CI·실험 구성에서 두 서비스와 의존성을 제거했다. 새 DB 초기화는 두 스키마를 생성하지 않는다.
- 환경변수 예제, Jenkins 테스트·이미지 정리, Prometheus·Grafana 대상을 함께 수정했다.
- Spring 모니터링 대상은 업무 7개와 Gateway·Eureka를 합한 9개다.
- 현재고·수량 조정·변경 원장 API와 감사 소비자의 중복 방지·DLT 처리는 더 이상 제공하지 않는다.
  해당 기능을 Menus·Notices 등의 구현으로 이름만 바꾸어 옮기지 않았다.
- Account의 DB/Outbox 트랜잭션과 Kafka 발행은 유지한다. 현재 업무 소비자는 없다.
  Jenkins와 실험 스크립트의 Kafka 확인 범위도 Outbox 발행까지로 변경했다.
- 기존 DB·데이터 볼륨에는 변경 명령을 실행하지 않았다. 삭제한 서비스의 코드·migration은 Git 이력에 남는다.

## 검증

- `python3 scripts/verify-service-architecture.py`: 통과.
- `python3 scripts/verify-service-architecture.py --ci`: 통과.
- `python3 scripts/verify-service-architecture.py --performance`: 통과.
- `python3 -m unittest discover -s performance -p 'test_*.py'`: 실험 볼륨 보호 3개 통과.
- 수정한 Python 파일 구문 검사와 Jenkins의 shell 블록 15개 구문 검사: 통과.
- 원격 Jenkins, 수정된 smoke의 실제 호출과 새 구성의 컨테이너 기동은 이번 변경에서 실행하지 않았다.
  Compose 설정 검증은 실제 기동·Eureka 등록·모니터링 UP 확인을 대신하지 않는다.

## 재발 방지 검토와 반영

세 가지 개선을 검토했다: 서비스 목록의 정확한 일치 검사, 과거 검증 결과의 적용 범위 표시,
데이터 보존을 포함한 기존 환경 전환 안내. 그중 목록 검사를 자동화하고 나머지 두 항목도 문서에 반영했다.
검증기는 추가 업무 폴더, 허용되지 않은 Compose 서비스, 모니터링 대상 불일치를 실패로 처리한다.
Jenkins의 Validate Compose 단계에도 연결했으며 이를 위한 Python 3를 Jenkins Dockerfile에 추가했다.
기존 Jenkins 이미지를 사용하는 환경은 변경된 Dockerfile로 이미지를 재빌드해야 한다.

2026-09-15의 `service-transition-results.md`와 검증 JSON, 과거 스프린트 수치는 당시 구성의 기록이다.
기존 감사·재고 검증을 현재 7개 서비스 구성의 실적으로 재사용하지 않는다.

## 기존 환경에 적용할 때

현재 실행 중인 환경은 이 코드 변경만으로 전환되지 않는다. 전환 절차는
[서비스 설계 기준](service-architecture.md#기존-환경-전환)을 따른다.
제거된 서비스의 컨테이너가 남지 않도록 orphan 정리가 필요하며 데이터 볼륨을 삭제하는 `-v`를 사용하지 않는다.
Compose의 orphan 제거 옵션은 [Docker 공식 문서](https://docs.docker.com/reference/cli/docker/compose/up/)에서 확인했다.
이번 작업에서는 기존 실행 환경의 중단·재배포·볼륨 삭제를 수행하지 않았다.
