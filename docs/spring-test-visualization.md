# Spring 테스트 분리와 Grafana 시각화

ErpMSA 9개 Spring 모듈과 기존 KostaErpServer의 테스트를 JUnit Jupiter 클래스 태그 `unit`과 `integration`으로 분리했다.
단위 테스트 결과와 단위 실행에서 수집한 JaCoCo 0.8.16 커버리지를 기존 Pushgateway·Prometheus로 전송한다.
대시보드: [Spring Unit Tests · Projects](http://127.0.0.1:3000/d/erpmsa-spring-unit-tests).

이 문서의 대시보드는 단위 테스트 전용이다. 본인 전체 검증 결과(단위 38건·통합 24건)와
Postman API·Swagger 문서는 [본인 검증 내역](http://127.0.0.1:3000/d/kosta-personal-verification)에서 구분하며,
실행 조건과 실제 결과는 [별도 기록](kosta-personal-verification.md)에 정리했다.

현재 KostaErpServer는 본인 작성 단위 테스트 8개 클래스·38건만 실행·전송한다.
로그인·통계 서비스와 휴대폰 인증을 독립 실행하도록 전환했다. 전체 39개 파일 재검토와 최신 38/24건 결과는 [분류 기록](kosta-test-classification.md)과 [실행 기록](kosta-personal-verification.md)을 참고한다. 아래 18·17건 측정은 이전 이력이다.

## 실행 방법

ErpMSA 저장소 루트에서 실행한다. Java 21, 각 모듈의 Gradle 9.5.1 Wrapper와 Python 표준 라이브러리를 사용한다.

```bash
# 단위 테스트 + JaCoCo + 로컬 Grafana 지표 갱신
python3 scripts/run-spring-tests.py --suite unit --pushgateway http://127.0.0.1:9091

# KostaErpServer 본인 작성 단위 테스트 38건 + JaCoCo + 프로젝트별 Grafana 지표
python3 scripts/run-spring-tests.py --project KostaErpServer --suite unit --pushgateway http://127.0.0.1:9091

# 통합 테스트만 실행: Testcontainers용 Docker 필요, Grafana 단위 지표는 변경하지 않음
python3 scripts/run-spring-tests.py --suite integration

# 두 그룹을 순서대로 실행
python3 scripts/run-spring-tests.py --suite all --pushgateway http://127.0.0.1:9091

# 특정 모듈만 실행
python3 scripts/run-spring-tests.py --suite unit --modules AccountService FoodMaterialsService --pushgateway http://127.0.0.1:9091

# Gradle로 직접 실행: 보고서 생성만 수행하며 지표 전송은 위 실행기를 이용
./AccountService/gradlew -p AccountService :unitTest
./AccountService/gradlew -p AccountService :integrationTest
./AccountService/gradlew -p AccountService :check
```

`test`는 `unit` 태그만 실행하고 `unitTest`는 그 작업의 별칭이다.
`integrationTest`는 같은 테스트 소스에서 `integration` 태그만 실행한다. `check`는 두 그룹을 모두 실행한다.
ErpMSA는 기존 검증문·업무 코드를 유지하고 태그로 분리했다. KostaErpServer의 독립 실행 전환과 추가 assertion은 별도 분류 기록에 명시한다.

Spring Boot 컨텍스트, 실제 HTTP 서버, DB·Redis·Kafka 연결 테스트는 통합 그룹으로 분류했다.
이름이 `ApplicationTests`인 클래스뿐 아니라 Spring 컨텍스트·HTTP 연결을 검증하는
`DisposalsService`의 `StockClientConfigurationTests`도 통합 그룹이다.
새 테스트 클래스에는 두 태그 중 하나를 지정해야 하며, 실행기는 누락 태그와 단위 그룹의 Spring 컨텍스트 테스트를 거절한다.

## 보고서와 지표의 의미

- 단위 JUnit XML: `<모듈>/build/test-results/test/`, HTML: `<모듈>/build/reports/tests/test/index.html`.
- 통합 JUnit XML: `<모듈>/build/test-results/integrationTest/`, HTML: `<모듈>/build/reports/tests/integrationTest/index.html`.
- 단위 JaCoCo XML: `<모듈>/build/reports/jacoco/test/jacocoTestReport.xml`, HTML: 같은 경로의 `html/index.html`.
- 실행별 요약·XML 복사본·로그·Prometheus 텍스트: `.verification/spring-tests/<project>/<run-id>/`. Git에서 제외한다. 11월 2일의 기존 실행은 프로젝트 하위 폴더가 없는 이전 경로에 보존했다.

실행기는 이전 생성 보고서와 단위 실행 데이터를 먼저 정리하므로 Gradle 시작 실패를 이전 성공 결과로 표시하지 않는다.
분류별 실제 보고 클래스가 예상 클래스와 일치하는지 검사하며, 누락·다른 그룹 혼입·보고서 파싱 오류는 실행 오류다.
실패·오류·건너뜀은 별도 집계한다. 성공률의 분모는 성공+실패+오류이며 건너뜀은 제외한다.

`integrationTest`에는 JaCoCo 에이전트를 사용하지 않고 단위 커버리지 보고서는 `test`의 실행 데이터만 읽는다.
ErpMSA 커버리지 범위는 각 루트 서비스의 `src/main`이며 `shared/jwt-security`, `shared/service-foundation`은 포함하지 않는다.
업무 클래스·컨트롤러·설정을 임의로 제외해 커버리지를 높이지 않았다. JaCoCo의 기본 생성 코드 필터는 적용된다.

단위 테스트가 없는 모듈은 `단위 테스트 없음`, 성공률·커버리지는 `—`로 표시한다.
전부 건너뛴 경우도 PASS와 구분하며, 측정되지 않은 커버리지를 0%나 100%로 채우지 않는다.
상단 커버리지는 **측정된 모듈만** 대상으로 줄·분기 카운터를 합산한 가중 비율이다. 서비스 비율의 단순 평균이 아니다.
커버리지는 코드 실행 범위이며 테스트의 정확성이나 업무 기능 완성도를 뜻하지 않는다.

Pushgateway job은 `spring_unit_tests`, 그룹 키는 `project`, `module`, `source`, `branch`다.
같은 그룹은 PUT으로 교체하고 `local`과 `jenkins`, 브랜치를 구분한다. OCR 지표는 변경하지 않는다.
대표 지표는 `erpmsa_unit_test_cases`, `erpmsa_unit_test_state`, `erpmsa_unit_test_coverage_ratio`,
`erpmsa_unit_test_coverage`, `erpmsa_unit_test_finished_timestamp_seconds`다.
실패 메시지·인식 원문 등은 지표에 넣지 않고 테스트 이름도 시계열 라벨로 사용하지 않는다.

Grafana의 새로고침은 마지막 보고값을 다시 조회하며 테스트를 다시 실행하지 않는다.
최신성을 확인하도록 실제 테스트 완료 시각과 가장 오래된 결과의 경과 시간을 표시한다.
프로젝트·실행 환경·브랜치·모듈 필터로 비교 범위를 선택할 수 있다.
프로젝트는 한 번에 하나를 선택하며 서로 다른 코드와 커버리지를 합산하지 않는다.
KostaErpServer의 현재 브랜치는 `develop`, ErpMSA는 `main`이며 프로젝트 변경 시 브랜치·모듈 목록도 갱신한다.

## Jenkins 연결

`Jenkinsfile`은 인프라 시작 전 `Spring Unit Tests` 단계에서 실행기를 호출한다.
이후 기존 테스트 인프라와 `Spring Integration Tests` 단계를 진행한다.
JUnit 게시 단계는 두 보고서 경로를 모두 수집하며 HTML·JaCoCo·요약·지표 텍스트를 아티팩트로 보관한다.

Jenkins에서 Grafana로 자동 전송하려면 Jenkins가 접근할 수 있는 **지속 운영 Pushgateway** 주소를
`SPRING_TEST_PUSHGATEWAY_URL` 환경변수로 설정한다. 미설정이어도 테스트와 Jenkins 보고서는 생성하며 지표 전송만 생략한다.
예를 들어 Jenkins가 기존 `erpmsa_default` 네트워크에 연결돼 있다면 `http://pushgateway:9091`을 사용할 수 있다.
임시 CI Compose의 Pushgateway를 지정하면 정리 시 결과가 사라지므로 그 주소는 사용하지 않는다.
이번 작업에서는 실제 Jenkins 빌드를 실행하지 않았으며, 로컬에서 동일한 Gradle 분리와 실행기를 검증했다.

## 실제 검증 결과: 2026-11-02

로컬 Mac, Java 21.0.10, Gradle 9.5.1, JaCoCo 0.8.16에서 측정했다.
기준 Git HEAD는 `6268d9cd4a9643b2f4526d0ceb3ce04a342ec6a7`이며 기존 미커밋 변경과 이번 변경이 포함된 상태다.
커밋·푸시는 수행하지 않았다.

- 단위 실행: `spring-unit-20261102`, 23:09:12~23:10:01 KST.
- 통합 실행: `spring-integration-20261102`, 23:12:57~23:14:18 KST.
- 단위 67건, 통합 52건 모두 통과, 실패·오류·건너뜀 0건.
- 24개 테스트 클래스가 단위 12개·통합 12개로 완전히 분리됐고 두 결과 집합의 교집합은 없다.
- 파라미터화된 테스트는 실행별 JUnit 사례 수로 계산하므로 소스의 `@Test` 개수와 다를 수 있다.

| 모듈 | 단위 사례 | 통합 사례 | 단위 줄 커버리지 | 단위 분기 커버리지 |
|---|---:|---:|---:|---:|
| AccountService | 31 | 4 | 62.44% (261/418) | 55.32% (52/94) |
| MenusService | 0 | 5 | — | — |
| FoodMaterialsService | 22 | 22 | 67.38% (283/420) | 53.70% (29/54) |
| NoticesService | 0 | 4 | — | — |
| BillsService | 0 | 4 | — | — |
| PurchaseService | 0 | 4 | — | — |
| DisposalsService | 0 | 7 | — | — |
| gatewayServer | 14 | 1 | 91.23% (52/57) | 94.44% (17/18) |
| eurekaServer | 0 | 1 | — | — |
| 합계 / 측정 3모듈 가중 비율 | 67 | 52 | 66.59% (596/895) | 59.04% (98/166) |

통합 테스트 후에도 단위 실행 시 복사한 JaCoCo XML과 현재 XML이 바이트 단위로 일치했다.
Testcontainers는 기존 테스트 설정의 임시 컨테이너·tmpfs·재사용 금지 구성을 사용했다.
`erpmsa.verification.run=spring-integration-20261102` 라벨의 실행 중 컨테이너가 남지 않았음을 확인했다.
기존 DB·볼륨은 초기화하지 않았다.

당시 수집기 자체의 파싱·분류·미측정·실행 실패·Git 상태 처리 테스트 11건도 별도로 통과했다.
이는 Spring 67건/52건 집계에는 포함하지 않는다.

서비스 구조 검증은 기본·CI·performance 세 구성에서 모두 통과했다.
Grafana 11개 패널의 쿼리 결과와 실제 렌더링을 확인했으며, 표에서 9개 모듈의 상태·커버리지·완료 시각을 확인했다.

```bash
python3 -m unittest discover -s scripts -p test_spring_tests.py
python3 scripts/verify-service-architecture.py
python3 scripts/verify-service-architecture.py --ci
python3 scripts/verify-service-architecture.py --performance
```

설정 근거: [Gradle JaCoCo 연동](https://docs.gradle.org/current/userguide/jacoco_plugin.html),
[JaCoCo 공식 배포](https://www.jacoco.org/jacoco/),
[JaCoCo 줄·분기 카운터](https://www.jacoco.org/jacoco/trunk/doc/counters.html),
[Jenkins JUnit 결과 게시](https://www.jenkins.io/doc/pipeline/tour/tests-and-artifacts/).


## KostaErpServer 추가: 2026-11-03

기본 경로는 ErpMSA의 형제 경로 `../2026_05_KOSTA/KostaErpServer`다. 다른 위치는
`--project-root /path/to/KostaErpServer`로 지정한다. 프로젝트별 Git 브랜치·HEAD·미커밋 상태를 기록한다.
Maven Wrapper는 `sh`로 실행하므로 기존 Wrapper 파일의 실행 권한을 변경하지 않는다.

```bash
# KostaErpServer 저장소에서: 단위 실행과 JaCoCo 보고서
sh ./mvnw test

# 격리된 테스트 DB와 fixture를 준비한 뒤: 통합만 / 단위+통합
sh ./mvnw -DskipUnitTests=true verify
sh ./mvnw verify
```

Surefire와 Failsafe는 Spring Boot 3.5.14 부모가 관리하는 3.5.5를 사용한다.
Surefire는 `unit`만, Failsafe는 `integration`만 실행하며 반대 태그를 명시적으로 제외한다.
Failsafe에는 단위 JaCoCo 에이전트를 전달하지 않는다. `test` 단계는 통합 테스트를 실행하지 않는다.
Maven effective POM에서 플러그인 버전·양쪽 태그·Failsafe 실행 단계·빈 `argLine`을 확인했다.

- 단위 XML: `target/surefire-reports/TEST-*.xml`.
- 통합 XML: `target/failsafe-reports/TEST-*.xml`.
- 단위 JaCoCo: `target/jacoco-unit.exec`, `target/site/jacoco-unit/jacoco.xml`, 같은 폴더의 `index.html`.
- 범위: KostaErpServer 전체 `src/main` 117개 분석 클래스. 임의 커버리지 제외는 없다.

기존 39개 테스트 파일에 태그를 추가했다. 활성 단위 클래스는 6개, 통합 클래스는 32개다.
나머지 1개 통합 클래스의 기존 `@Test`는 모두 주석 상태여서 실행 건수에 포함하지 않는다.
39개 파일은 태그를 제거하면 작업 전 SHA-256과 일치하므로 기존 검증문·주석 상태를 유지했다.
HTTP 클라이언트의 `MockRestServiceServer`는 실제 소켓/서버 없이 요청을 모의하므로 단위 그룹이다.
단위 그룹에 Spring 컨텍스트나 실제 HTTP 서버 테스트가 들어오면 수집기가 거절한다.
수집기는 주석 속 `@Test`를 제외하며 파일명과 실제 클래스명이 다른 기존 테스트도 실제 선언명으로 검사한다.

| 프로젝트 / 실행 | 단위 결과 | 줄 커버리지 | 분기 커버리지 | 기준 |
|---|---:|---:|---:|---|
| ErpMSA / `erpmsa-unit-20261103` | 67/67, 실패·오류·건너뜀 0 | 66.59% (596/895) | 59.04% (98/166) | 측정된 3모듈, 단위 테스트 없는 6모듈은 — |
| KostaErpServer / `kosta-unit-20261103` | 18/18, 실패·오류·건너뜀 0 | 10.41% (190/1,825) | 14.09% (62/440) | 전체 프로젝트 코드 |

KostaErpServer는 Java 21.0.10 / Maven 3.9.15 / JaCoCo 0.8.16에서 실행했다.
기준 HEAD는 `de614b1e49534de279dd3be9e9f0acf06cf6ac74`, 브랜치는 `develop`이며 이번 미커밋 변경이 포함됐다.
측정 범위와 코드가 다르므로 두 커버리지 수치를 마이그레이션 전후의 개선율로 해석하지 않는다.

통합 테스트 소스는 단위 실행의 `test-compile`에서 함께 컴파일했다.
실제 DB에 연결하는 통합 테스트는 실행하지 않았다. 기존 테스트 프로필은 `DB_URL`·`DB_USERNAME`·`DB_PASSWORD`와
`ddl-auto: update`를 사용하고 일부 사례는 기존 업무 데이터에 의존한다. 전체 통합 사례를 재현할 schema/seed SQL은
현재 저장소에 없어 격리 DB와 fixture를 준비해야 한다. 기존 DB·볼륨은 변경하지 않았다.

프로젝트별로 17개 패널 쿼리가 모두 성공했고, Grafana에서 프로젝트를 전환할 때
`main`/`develop` 브랜치와 67건/18건 결과·커버리지가 함께 갱신되는 것을 확인했다.
수집기 회귀 테스트 15건과 ErpMSA 서비스 구조의 기본·CI·performance 검증도 통과했다.
실제 Jenkins 빌드·운영 배포·커밋·푸시는 수행하지 않았다.

설정 근거: [Surefire JUnit 태그 필터](https://maven.apache.org/surefire/maven-surefire-plugin/examples/junit-platform.html),
[Failsafe JUnit 태그 필터](https://maven.apache.org/surefire/maven-failsafe-plugin/examples/junit-platform.html),
[JaCoCo Maven 에이전트·보고서](https://www.jacoco.org/jacoco/trunk/doc/maven.html).

## 본인 작성 단위 테스트만 재측정: 2026-11-03

사용자 요청에 따라 KostaErpServer의 현재 Grafana 결과를 본인 작성 테스트만 실행한 결과로 교체했다.
위의 전체 18건 결과는 이전 측정 이력이다. 공통 실행기의 KostaErpServer 단위 실행·전송은 이제 다음 5개 클래스만 선택한다.
Git 이력의 본인 명의와 테스트 본문을 대조해 고정한 목록이며, 명의만으로 직접 수기 작성 여부까지 증명하지는 않는다.

| 클래스 | 실제 실행·성공 |
|---|---:|
| `dto.ocr.BusinessRegistrationResponseTest` | 4 |
| `service.BusinessDocumentVerificationServiceTest` | 6 |
| `service.RegistrationServiceTest` | 3 |
| `service.client.BusinessRegistrationClientTest` | 3 |
| `service.client.PythonOcrClientTest` | 1 |
| 합계 | 17 |

재현 명령은 기존과 같다. Maven 기본 `sh ./mvnw test`의 전체 단위 범위는 유지하며,
공통 실행기만 `-Dtest=<선택한 5개 클래스의 전체 이름>`으로 실제 실행 범위를 제한한다.
새 클래스 추가는 본인 작성 여부를 확인한 뒤 `KOSTA_PERSONAL_UNIT_TESTS` 목록에 반영해야 한다.

```bash
python3 scripts/run-spring-tests.py --project KostaErpServer --suite unit --pushgateway http://127.0.0.1:9091
```

실행 ID는 `kosta-personal-unit-20261103`, 실행 시간은 00:23:09~00:23:12 KST다.
Java 21.0.10 / Maven 3.9.15 / JaCoCo 0.8.16과 기존 HEAD `de614b1e49534de279dd3be9e9f0acf06cf6ac74`의 미커밋 상태에서 측정했다.

- 17건 전부 통과, 실패·오류·건너뜀 0건. 보고 클래스는 선택한 5개와 정확히 일치한다.
- 줄 커버리지: **177/1,825 = 9.70%**.
- 분기 커버리지: **52/440 = 11.82%**.
- 커버리지 분모는 이전과 같은 전체 `src/main` 117개 클래스다. 본인 작성 코드만으로 분모를 축소하지 않았다.
- 실행 전 기존 단위 XML·JaCoCo exec·보고서를 정리했으며, 제외한 폐기 서비스의 줄 커버리지가 0임을 확인했다.
- 기존 39개 테스트 소스와 `pom.xml`은 이번 재측정 전 파일 해시와 일치한다. 테스트를 삭제하거나 검증문을 바꾸지 않았다.

Pushgateway의 동일한 `project=KostaErpServer,module=KostaErpServer,source=local,branch=develop` 그룹을 PUT으로 교체했다.
따라서 현재 프로젝트 결과는 18건과 합산되지 않는다. `erpmsa_unit_test_info`에는
`test_selection=personal-kosta-unit`과 실제 실행 ID를 기록한다. 이전 18건의 보고서·실행 아티팩트는 보존했다.
Prometheus에서 17건과 새 실행 ID를 확인했고, ErpMSA 9개 모듈의 건수·완료 시각은 이전 값과 일치했다.
Grafana 상단에 프로젝트별 측정 범위를 표시한다. 실제 렌더링에서 KostaErpServer 17건·실패 0건·성공률 100%·줄 9.7%·분기 11.8%를 확인했다.
수집기의 선택 목록·목록 누락 처리 회귀 검증을 포함한 Python 테스트 17건도 별도로 통과했다.
이는 KostaErpServer JUnit 17건에 포함하지 않는다.
실제 DB에 연결하는 통합 실행·Jenkins 빌드·운영 배포·커밋·푸시는 수행하지 않았다.

명령 근거: [Surefire 테스트 클래스 선택](https://maven.apache.org/surefire/maven-surefire-plugin/examples/single-test.html).


2026-11-03 표시 조정: `모듈별 단위 테스트 결과` 그래프는 전체 테스트 건수가 0인 모듈을 쿼리에서만 숨긴다. 원본 지표·모듈·상단 요약·상세 표는 유지하며, 실행된 모듈의 실패·오류·건너뜀도 함께 표시한다.

2026-11-03 표시 선택 추가: Grafana 상단의 **0건 모듈**에서 **숨김**(기본값) 또는 **표시**를 선택한다.
`모듈별 단위 테스트 결과` 그래프에만 적용하며, 숨김은 ErpMSA 실행 모듈 3개, 표시는 전체 9개 모듈을 보여준다.
원본 지표·상단 요약·상세 표와 KostaErpServer 본인 테스트 17건은 유지한다.
선택은 URL 변수에 반영되므로 선택이 포함된 링크를 다시 열면 해당 선택을 사용한다.
새 선택이 없는 기본 대시보드 링크는 숨김으로 시작한다.
실제 Grafana 화면에서 기본 숨김, 표시 선택 시 9개 모듈, 숨김 재선택 시 3개 모듈 전환을 확인했다.
두 프로젝트의 표시·숨김 쿼리 4개 조합도 모두 정상이며 원본 데이터는 변경하지 않았다.
설정 근거: [Grafana 사용자 정의 변수](https://grafana.com/docs/grafana/latest/visualizations/dashboards/variables/add-template-variables/).
