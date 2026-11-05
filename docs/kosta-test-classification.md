# KostaErpServer 본인 테스트 재분류

2026-11-03 기준 전체 `src/test` Java 파일 **39개**를 메서드 본문과 Git 이력으로 다시 확인했다. 본인 업무 테스트는 13개 클래스 **62건**이며 단위 8개 클래스 **38건**, 통합 5개 클래스 **24건**으로 분리한다. 기본 생성 컨텍스트 확인 1건은 별도 실행한다.

## 작성 범위 확인

`HEAD`의 메서드 본문 작성자가 `jong845`·`JongHwan`인지 확인했다. 본인 이름의 import 변경만 있는 파일에서 팀원 테스트를 가져오지 않는다. 전환한 테스트의 메서드명·기존 assertion은 유지했고 Mock 설정, DAO 전달값·호출 검증은 이번 보완이다. Git 명의는 수기 작성 여부까지 증명하지 않는다.

전체 실행기는 모든 파일을 다시 검사해 새 본인 테스트가 선택 목록에서 빠지거나 팀원 테스트가 들어오면 오류로 처리한다. 소스 해시와 원본 메서드 목록은 실행별 `summary.json`의 `testInventory`에 보존한다.

## 실제 의존성에 따른 분리

| 클래스 | 건수 | 현재 그룹 | 검증 대상 |
|---|---:|---|---|
| `BusinessRegistrationResponseTest` | 4 | unit | 기존 독립 실행 검증 유지 |
| `StatisticsDAOTest` | 11 | integration | 실제 MyBatis SQL 실행 (기존 결과 로깅) |
| `UserinfoDAOTest` | 7 | integration | 실제 SQL, 메서드별 합성 사전 데이터 격리 |
| `AdminUserDAOTest` | 1 | integration | 실제 관리자 저장·조회 |
| `RegistrationRequestedUserRepositoryTest` | 3 | integration | 실제 신청 저장·조회·잠금 조회 |
| `AuthServiceTest` | 7 | unit | LoginServiceImpl 직접 생성, DAO·계정 서비스·인코더 Mock. 사용자 매핑·계정 생성 위임 검증 |
| `BusinessDocumentVerificationServiceTest` | 6 | unit | 기존 독립 실행 검증 유지 |
| `PhoneVerificationServiceTest` | 3 | unit | 기존 DAO·발송 Stub 유지, 불필요한 Spring·트랜잭션 설정 제거 |
| `RegistrationReviewServiceTest` | 2 | integration | 실제 승인·반려와 저장 상태 확인 |
| `RegistrationServiceTest` | 3 | unit | 기존 독립 실행 검증 유지 |
| `StatisticsServiceTest` | 11 | unit | StatisticsServiceImpl 직접 생성, DAO Mock. 조회 인자·반환값·폐기 품목 변환 검증 |
| `BusinessRegistrationClientTest` | 3 | unit | 기존 독립 실행 검증 유지 |
| `PythonOcrClientTest` | 1 | unit | 기존 독립 실행 검증 유지 |

SQL 실행·저장 상태 확인이 목적인 레포지토리 테스트는 통합 그룹에 둔다. 가입 심사 2건도 실제 트랜잭션 환경에서 승인·반려 후 저장 상태를 확인하므로 통합으로 유지한다. 서비스 18건은 이번에 DAO 경계에서 격리한 단위 테스트로 전환했으므로 과거의 DB 연결 실행과 검증 범위를 구분한다.

## 전체 파일 검토 내역

| 파일 | 활성 원본 메서드 | 집계 범위 | 현재 분류 |
|---|---:|---|---|
| `KostaErpServerApplicationTests.java` | 1 | 생성된 기본 확인 (별도) | integration |
| `dto/ocr/BusinessRegistrationResponseTest.java` | 4 | 본인 업무 | unit |
| `repository/AddFoodMaterialDAOTest.java` | 15 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `repository/AddMenuDAOTest.java` | 15 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `repository/DisposalDAOTest.java` | 17 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `repository/FoodMaterialDAOTest.java` | 7 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `repository/MenuDAOTest.java` | 1 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `repository/NoticeDAOTest.java` | 9 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `repository/StatisticsDAOTest.java` | 11 | 본인 업무 | integration |
| `repository/UserinfoDAOTest.java` | 7 | 본인 업무 | integration |
| `repository/entity/AdminUserDAOTest.java` | 1 | 본인 업무 | integration |
| `repository/entity/ExpNoticeDAOTest.java` | 4 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `repository/entity/ExpirationNoticeDAOTest.java` | 2 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `repository/entity/OutOfStockNoticeDAOTest.java` | 4 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `repository/entity/PurchaseDAOTest.java` | 1 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `repository/entity/RegistrationRequestedUserRepositoryTest.java` | 3 | 본인 업무 | integration |
| `repository/entity/SalesRecordDAOTest.java` | 1 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `repository/entity/StockNoticeSettingDAOTest.java` | 4 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `service/AddFoodMaterialServiceTest.java` | 18 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `service/AddMenuServiceTest.java` | 12 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `service/AuthServiceTest.java` | 7 | 본인 업무 | unit |
| `service/BusinessDocumentVerificationServiceTest.java` | 6 | 본인 업무 | unit |
| `service/DisposalServiceTest.java` | 1 | 팀원 또는 주석 상태 (집계 제외) | unit |
| `service/ExpNoticeServiceTest.java` | 3 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `service/ExpStockNoticeSettingServiceTest.java` | 2 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `service/ExpirationNoticeServiceTest.java` | 3 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `service/FoodMaterialServiceTest.java` | 5 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `service/MenuServiceTest.java` | 1 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `service/NoticeServiceTest.java` | 11 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `service/PhoneVerificationServiceTest.java` | 3 | 본인 업무 | unit |
| `service/RegistrationReviewServiceTest.java` | 2 | 본인 업무 | integration |
| `service/RegistrationServiceTest.java` | 3 | 본인 업무 | unit |
| `service/StatisticsServiceTest.java` | 11 | 본인 업무 | unit |
| `service/StockNoticeSettingServiceTest.java` | 3 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `service/client/BusinessRegistrationClientTest.java` | 3 | 본인 업무 | unit |
| `service/client/PythonOcrClientTest.java` | 1 | 본인 업무 | unit |
| `service/entity/OutOfStockNoticeServiceTest.java` | 5 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `service/entity/PurchaseServiceTest.java` | 2 | 팀원 또는 주석 상태 (집계 제외) | integration |
| `service/entity/SalesRecordServiceImplTest.java` | 0 | 팀원 또는 주석 상태 (집계 제외) | inactive |

## 실행과 Grafana

```bash
# ErpMSA 저장소에서 본인 전체 검증·지표 갱신
python3 scripts/run-kosta-personal-verification.py --run-id <고유한-실행-ID>

# 본인 단위 38건·JaCoCo만 다시 측정
python3 scripts/run-spring-tests.py --project KostaErpServer --suite unit --pushgateway http://127.0.0.1:9091
```

단위 실행은 DB 주소를 연결 불가능한 로컬 포트로 고정해 개발 DB 환경과 분리한다. 통합은 새 tmpfs MariaDB와 합성 schema/fixture에서 실행하고 종료 후 제거한다. 운영 DB·기존 볼륨을 사용하지 않는다. 단위 XML·JaCoCo는 통합 실행 전후 해시를 비교하며 통합·API 실행 데이터를 단위 커버리지에 합산하지 않는다.

Grafana [본인 검증 내역](http://127.0.0.1:3000/d/kosta-personal-verification)에 단위·통합의 클래스별 결과와 단위 커버리지를 표시한다. [프로젝트별 단위 결과](http://127.0.0.1:3000/d/erpmsa-spring-unit-tests)는 본인 단위 38건을 표시한다.

기존 17건 결과는 이전 분류의 측정 이력이며 현재 단위 범위는 38건이다. Postman 기록/재검증과 Swagger 문서 확인은 테스트 분류와 별도 유지한다. 커밋·푸시는 하지 않는다.
