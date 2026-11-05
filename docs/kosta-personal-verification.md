# KostaErpServer 본인 작성 테스트·API·문서화 검증

## 현재 결과: 본인 전체 테스트 재분류 (2026-11-03)

전체 테스트 파일 39개를 메서드 본문·Git 작성 이력과 실제 의존성으로 다시 검토했다.
본인 업무 테스트 **62건 = 단위 38건 + 통합 24건**이다. 기본 생성 `contextLoads` 1건은 별도 확인한다.
[전체 분류 근거와 파일별 검토](kosta-test-classification.md)를 참고한다.

| 측정 | 현재 실행 결과 |
|---|---:|
| 본인 단위 테스트 (8개 클래스) | **38/38 통과** |
| 본인 통합 테스트 (5개 클래스) | **24/24 통과** |
| 생성된 컨텍스트 확인 (업무 집계 제외) | 1/1 통과 |
| 단위 JaCoCo 줄 | **16.49% (301/1825)** |
| 단위 JaCoCo 분기 | **20.00% (88/440)** |
| Postman API 재검증 | 8/8 통과, assertion 16개 |
| Swagger 문서 / 설정 확인 | 14/14 경로, 5/5 설정 |

휴대폰 인증 3건은 기존 Stub을 유지하고 Spring 설정을 제거했다. 로그인 서비스 7건과 통계 서비스 11건은
DAO·계정 서비스 등을 Mock으로 대체하고 실제 서비스 객체를 직접 생성한다. 기존 테스트 메서드와 assertion은 유지하고
DAO 인자·반환값과 회원 매핑·폐기 품목 변환 assertion을 보완했다. 이번 보완을 과거 사용자 작성 내역으로 소급하지 않는다.
실제 SQL·저장 상태를 확인하는 레포지토리와 가입 심사는 통합으로 유지한다.

실행 ID: `kosta-reclassified-20261103-r1` / 단위 하위 실행: `kosta-reclassified-20261103-r1-unit`.
실행 시간: 2026-11-03T09:58:53+09:00 ~ 2026-11-03T10:00:11+09:00.
전체 `src/main` 117개 클래스·1,825줄·440분기를 같은 분모로 사용했다.
단위 측정 범위가 17건에서 38건으로 늘어난 재측정이므로 커버리지 변화만으로 코드 품질 개선을 단정하지 않는다.
단위 XML은 통합·API 실행 전후 SHA-256이 동일했고 임시 DB·앱·인증 파일은 정리했다.
실제 DB·기존 볼륨은 사용하지 않았고 커밋·푸시는 하지 않았다.

```bash
# ErpMSA 저장소에서 전체 검증·JaCoCo·Grafana 갱신
python3 scripts/run-kosta-personal-verification.py --run-id <고유한-실행-ID>

# 본인 단위 38건만 재측정
python3 scripts/run-spring-tests.py --project KostaErpServer --suite unit --pushgateway http://127.0.0.1:9091
```

Grafana의 단위 표는 8개 클래스, 통합 표는 5개 클래스와 별도 컨텍스트 확인을 표시한다.
같은 Pushgateway 그룹을 PUT으로 갱신해 이전 DB 그룹에 있던 로그인·통계 서비스·휴대폰 인증 수치는 남기지 않는다.
통합 결과에는 `suite="integration"`, 기본 확인에는 별도 지표를 사용한다. 클래스별 단위 결과도 실제 JUnit XML로 게시한다.

최초 재분류 실행은 임시 계정 스키마의 중복 생성으로 실패했고 DB는 정리됐다.
중복 생성 제거 후 위 실행 ID에서 전체가 통과했다. 실패 아티팩트는 보존한다.

최종 검증: Grafana 본인 대시보드 24개·프로젝트별 단위 대시보드 17개 쿼리가 모두 정상 응답했다.
실제 렌더링에서 단위 표 8개 클래스와 통합 표 5개 클래스·기본 확인 1개를 확인했다.
ErpMSA 기존 단위 67건과 모듈별 완료 시각은 그대로이며, 이전 통합 그룹의 서비스·휴대폰 중복 지표는 교체됐다.
실행기 Python 회귀 테스트 32건과 서비스 구조 검증 기본·CI·performance가 통과했다.
회귀 테스트 32건은 본인 Java 테스트 62건에 합산하지 않는다. 기존 39개 Java 테스트·pom.xml 중 실제 수정은 독립 실행 전환한 서비스 테스트 3개뿐이다.

## 이전 분류·측정 이력

아래 17·22·23건은 재분류 전 결과이며 현재 실행 범위는 위 38·24건이다.

[Grafana: KostaErpServer · 본인 검증 내역](http://127.0.0.1:3000/d/kosta-personal-verification)

기존 단위 테스트 17건과 통계 서비스·레포지토리 테스트 22건, 로그인·가입 관련 DB 연결 테스트 23건,
Postman 요청 이력·이번 API 재검증, Swagger 문서화를 구분한다.
통계 테스트는 원본 `@SpringBootTest` 코드를 유지해 DB 연결 그룹에서 실행했다. 단위 JaCoCo에는 합산하지 않는다.
커밋·푸시·운영 배포는 수행하지 않았다.

## 본인 작성 범위와 제외 기준

검토한 Git 명의는 `jong845`·`JongHwan`이다. 명의만으로 직접 수기 작성 여부까지 증명하지는 않는다.

| 구분 | 범위 | Git 근거 |
|---|---|---|
| 통계 서비스 테스트 | `service/StatisticsServiceTest.java`, 활성 `@Test` 11개 | 최초 추가 `01f1007`, 현재 테스트 본문 본인 명의 |
| 통계 레포지토리 테스트 | `repository/StatisticsDAOTest.java`, 활성 `@Test` 11개 | 최초 추가 `5b4cda5`, 현재 테스트 본문 본인 명의 |
| Postman API 범위 | 로컬 요청 로그에 있는 통계 GET API 8개만 재검증 | 본인 통계 컨트롤러의 경로·서비스 위임 코드와 대조 |
| Swagger 통계 문서 | 본인 통계 컨트롤러의 GET 경로 13개 | 최초 컨트롤러 추가 `de79e5e` |
| Swagger 로그인 문서 | `OpenApiConfig`의 명시적 로그인 요청·응답·인증 설정 | 최초 추가 `31215c8`, 현재 파일 본인 명의 |

통계 컨트롤러에는 팀원의 공통 인증 정보 주입 변경도 포함되어 있다.
Git blame으로 본인 작성 경로 선언 13개와 통계 서비스 호출 13개를 확인했으며, 컨트롤러 전체와 인증 변경을 단독 기여로 집계하지 않는다.
다른 팀원의 폐기·알림·구매 테스트와 통계 외 API는 이 대시보드에 포함하지 않는다.

## 격리 실행

ErpMSA 저장소에서 실행한다. Java 21, Python 표준 라이브러리, Docker, Node/npm이 필요하다.

```bash
python3 scripts/run-kosta-personal-verification.py

# 경로·로컬 Postman 로그를 직접 지정할 경우
python3 scripts/run-kosta-personal-verification.py \
  --project-root /path/to/KostaErpServer \
  --postman-log /path/to/renderer-requester.log
```

실행기는 다음 순서로 동작한다.

1. 검토 대상 코드의 작성 이력·해시와 로컬 Postman 요청 경로만 수집한다. 원문 헤더·토큰·개인정보는 지표에 넣지 않는다.
2. 기존 DB·볼륨과 분리된 `mariadb:10.11` 컨테이너를 새로 만든다. DB는 tmpfs에 저장하고 포트는 localhost 임의 포트에만 연다.
3. `scripts/fixtures/kosta-statistics.sql`의 최소 조회 스키마와 합성 fixture를 로드한다. 운영 데이터 복사나 기존 DB 초기화는 하지 않는다.
4. `DB_URL` 등 환경변수를 이 컨테이너로 지정하고 Hibernate DDL 변경을 끈다.
5. Maven Failsafe의 `-Dit.test`로 본인 통계 2개 클래스와 로그인·가입 관련 6개 클래스를 선택한다. 단위 단계와 JaCoCo 에이전트를 실행하지 않는다.
6. 같은 격리 DB를 사용하는 애플리케이션을 localhost 임의 포트에서 시작한다.
7. 본인 작성 Swagger 문서 범위를 읽고, 기록의 8개 GET API를 재구성한 Postman v2.1 컬렉션을 Newman 6.2.1로 실행한다.
8. 애플리케이션·임시 DB를 종료하고 임시 JWT·인증 환경 파일·원본 Newman 보고서를 지운다. 민감 항목을 제외한 결과만 보관·전송한다.

Postman 재검증에는 원래의 외부 토큰·실제 요청 데이터·원래 서버 주소를 사용하지 않는다.
이 실행에서 만든 임시 JWT와 합성 데이터만 사용하며 Postman 클라우드 로그인·업로드는 하지 않는다.
Newman은 npm의 공개 패키지를 실행하는 도구 의존성이다. 기존 애플리케이션 의존성은 변경하지 않는다.

기존 단위 JaCoCo XML의 실행 전후 SHA-256을 비교한다. 통계·API 실행으로 단위 커버리지를 높여 표시하지 않는다.
API 재검증은 최소 합성 스키마에서 수행하므로 운영 스키마 전체의 migration·제약조건 호환성 검증은 아니다.

## 실제 결과: 2026-11-03

실행 ID: `kosta-personal-verification-20261103-r1`.
실행 시간: **01:01:55~01:02:14 KST**.
Java 21.0.10, Maven 3.9.15, MariaDB 10.11, Newman 6.2.1에서 실행했다.
기준 HEAD는 `de614b1e49534de279dd3be9e9f0acf06cf6ac74`, 브랜치는 `develop`이며 기존 미커밋 변경이 포함된 상태다.

| 구분 | 결과 | 의미 |
|---|---:|---|
| 기존 본인 단위 테스트 | 17/17, 기존 결과 유지 | 이번에 재실행한 22건과 별도 |
| 통계 서비스 테스트 | **11/11 통과** | 실패·오류·건너뜀 0 |
| 통계 레포지토리 테스트 | **11/11 통과** | 실패·오류·건너뜀 0 |
| 과거 Postman 요청 기록 | **8개 경로 발견** | 과거 성공 응답을 확인한 수가 아님 |
| 이번 Postman/Newman API 재검증 | **8/8 통과** | 각 HTTP 200, 예상 데이터·사업장 분리 검증. 검증문 총 16개 |
| Swagger 본인 문서 경로 | **14/14 확인** | 통계 자동 문서 13개 + 명시적 로그인 문서 1개 |
| Swagger 설정 확인 | **5/5 확인** | OpenAPI 3, JWT 명세, 로그인 요청 스키마, 응답 헤더, Swagger UI HTTP 응답 |

본인 단위 17건의 줄 커버리지 9.70%(177/1,825), 분기 11.82%(52/440)는 유지했다.
단위 JaCoCo XML은 바이트 단위로 실행 전과 일치했다.
기존 39개 Java 테스트 소스와 `pom.xml`도 이번 작업 전 해시와 일치한다.
임시 DB 컨테이너가 제거됐으며 별도 애플리케이션 프로세스도 종료했다.

### 기존 테스트의 검증 조건

서비스 11건은 `assertNotNull`로 결과 존재 여부를 확인한다.
레포지토리 11건은 조회 결과를 로그로 출력하며 명시적 예상값 assertion은 없다.
따라서 이 22건의 통과를 모든 통계 수치의 정확성 검증으로 표현하지 않는다.
이번 재구성 API 컬렉션에 합성 데이터 예상값과 다른 사업장 데이터 제외 여부를 검증하는 조건을 추가했다.
이 조건을 과거 사용자가 작성했던 Postman 자동 검증문이라고 소급해서 표시하지 않는다.

### Postman 구분

| 기록과 재검증에 포함한 경로 | 과거 자료 | 이번 실행 |
|---|---|---|
| `/api/statistics/disposals/rate` | GET 요청 기록 | 200·예상값 통과 |
| `/api/statistics/disposals/top-materials` | GET 요청 기록 | 200·예상값 통과 |
| `/api/statistics/disposals/reason-ratio` | GET 요청 기록 | 200·예상값 통과 |
| `/api/statistics/disposals/daily-chart` | GET 요청 기록 | 200·예상값 통과 |
| `/api/statistics/expenses/material-rank` | GET 요청 기록 | 200·예상값 통과 |
| `/api/statistics/expenses/material-rank/chart` | GET 요청 기록 | 200·예상값 통과 |
| `/api/statistics/revenue/history` | GET 요청 기록 | 200·예상값 통과 |
| `/api/statistics/revenue/menu-rank` | GET 요청 기록 | 200·예상값 통과 |

로컬 Postman 로그가 없는 다른 환경에서는 요청 이력은 미확인으로 표시하고 현재 API 재검증과 구분한다.

## Grafana와 결과 보관

별도 Pushgateway job `kosta_personal_verification`을 사용한다. 기존 `spring_unit_tests`와 OCR 지표는 변경하지 않는다.
`project=KostaErpServer`, `scope=personal`, `source=local`, 실제 브랜치 라벨로 범위를 구분한다.
테스트 결과, 과거 요청 발견, 이번 API 재검증, 문서 존재·설정 확인은 서로 다른 지표다.
Swagger 경로 수를 테스트 실행 건수에 합산하거나 과거 요청 발견을 PASS로 표시하지 않는다.

보고서는 `.verification/kosta-personal/<run-id>/`에 저장하며 Git에서 제외한다.

- `summary.json`: 출처·해시·실제 결과·임시 DB 정리 여부.
- `TEST-*.xml`: 원본 통계 테스트 JUnit 결과 2개.
- `postman-replay.collection.json`: 이번 재구성 컬렉션. 인증 값은 없고 환경변수 자리만 있다.
- `metrics.prom`: Grafana 수집 지표.
- Maven·Newman·애플리케이션 로그: 임시 fixture 실행 진단 자료.

대시보드의 20개 쿼리가 모두 정상 응답했으며 실제 화면에서 구분별 집계·API 8개 표·Swagger 14개 경로와 5개 설정 확인을 검증했다.
실행기 회귀 테스트 6건과 서비스 구조 검증 기본·CI·performance도 통과했다. 실행기 회귀 테스트는 사용자 JUnit 건수에 포함하지 않는다.

도구 근거: [Postman Newman 컬렉션 실행](https://learning.postman.com/docs/reference/newman-cli/command-line-integration-with-newman/).


## 로그인·회원가입 범위 보완: 2026-11-03

로그인·회원정보 테스트가 기존 단위 17건에 모두 포함된 것은 아니므로 다음 본인 작성 테스트를 별도로 추가 실행했다.

| 클래스 | 대상 | 실행·통과 |
|---|---|---:|
| `AuthServiceTest` | `LoginServiceImpl`의 로그인·회원가입·회원 확인·비밀번호 변경/찾기 | 7/7 |
| `UserinfoDAOTest` | 회원 레포지토리의 동일 기능 | 7/7 |
| `PhoneVerificationServiceTest` | 휴대폰 인증·기등록·재발송 제한 | 3/3 |
| `RegistrationReviewServiceTest` | 가입 승인·반려 | 2/2 |
| `RegistrationRequestedUserRepositoryTest` | 가입 신청 저장·대기 조회·잠금 조회 | 3/3 |
| `AdminUserDAOTest` | 관리자 저장·조회 | 1/1 |
| 합계 | 추가 DB 연결 그룹 | **23/23** |

`RegistrationServiceTest` 3건은 원래 단위 17건에 이미 포함되어 있어 중복 합산하지 않는다.
원본 `@SpringBootTest` 설정을 유지한 클래스는 DB 연결 그룹에서 실행한다.
서비스의 `@Transactional` 메서드도 포함해 실제 JUnit 실행 사례 수로 계산한다.

회원 DAO는 로그인에서 `test123`, `checkMemberByVO`에서 `kim123!` 등 서로 다른 사전 비밀번호를 요구한다.
실행 순서나 다른 테스트의 비밀번호 변경에 의존하지 않도록 **7개 메서드를 각각 별도 실행하고 합성 데이터를 초기화했다**.
이는 fixture 사전 조건을 독립적으로 준비한 것이며, 원본 쿼리·검증문·테스트 본문은 수정하지 않았다.
`kosta-account.sql`의 회원·계정·가입 신청·관리자 최소 스키마는 폐기 가능한 DB에만 로드한다.
운영 비밀번호·실제 사용자 데이터는 사용하지 않았다.

실행 ID는 `kosta-personal-with-account-20261103`다.
실행 시간은 2026-11-03T01:21:04+09:00 ~ 2026-11-03T01:22:23+09:00다.
통계 22건도 함께 다시 통과했고, Postman 재검증 8개·Swagger 문서 14개/설정 5개도 재확인했다.
기존 단위 커버리지 XML은 그대로이며 임시 앱·DB·인증 파일을 정리했다.
기존 본인 단위 17건 + 통계 DB 22건 + 계정 관련 DB 23건으로 업무별 검증 범위를 구분한다.
기본 생성 `contextLoads` 1건과 팀원 테스트는 추가 집계하지 않는다.
실행기 회귀 테스트는 선택·fixture 독립성 검증을 포함해 8건 통과했다.
커밋·푸시는 하지 않았다.
