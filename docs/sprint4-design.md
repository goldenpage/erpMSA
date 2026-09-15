# 4차 스프린트 설계 결정

목표는 기존 인증·품목·재고·감사 흐름의 권한 경계와 운영 한계를 설명하고 검증하는 것이다.
신규 주문 서비스, Kubernetes 전환, 운영 환경 배포는 이 스프린트에 포함하지 않는다.

## JWT: 서명 권한 분리

세 대안을 비교했다.

| 대안 | 장점 | 비용·위험 | 결정 |
|---|---|---|---|
| 공통 HS256 키 | 간단한 배포 | 검증 서비스도 서명 가능, 키 배포 범위가 큼 | 대체 |
| RS256 공개키 파일 묶음 | 검증에 인증 서버 통신 불필요, 단순한 장애 경계 | 교체 시 명시적 재배포 필요 | 이번 스프린트 선택 |
| JWKS 원격 조회 | 공개키 배포 자동화 가능 | 캐시·타임아웃·콜드스타트·unknown kid 요청 폭주 정책 필요 | 필요 시 후속 확장 |

`shared/jwt-security`는 네 서비스가 동일한 RS256/issuer/audience/만료/token_type 규칙을 쓰게 한다.
키 ID는 신뢰된 공개키 map 조회에만 사용하고 파일 경로나 URL로 해석하지 않는다.
검증에 실패해도 HS256이나 검증 생략으로 fallback하지 않는다. 공개키가 없거나 깨졌으면 시작에 실패한다.
서비스가 시작된 후 파일이 사라져도 이미 읽은 공개키로 검증한다. 이는 파일 삭제만으로 즉시 폐기되지
않는다는 뜻이므로 정상 교체·긴급 폐기를 구분한다.

### 생성과 접근

```bash
./scripts/generate-jwt-keys.sh local-k1
```

개인키는 PKCS#8 PEM, 공개키는 X.509 PEM이다. 생성기는 RSA 3072비트를 사용하며 검증기는 2048비트 미만을 거절한다.
개인키 부모 디렉터리는 호스트에서 0700이다. Compose file secret의 bind mount는 uid/gid 변경을
지원하지 않으므로 파일은 읽기 전용 0444로 두되, 호스트에서는 0700 부모 디렉터리로 접근을 제한한다.
부모 디렉터리를 공개 경로로 옮기거나 통째로 다른 서비스에 마운트하지 않는다.
개인키는 AccountService에만 `/run/secrets/jwt_private_key`로 연결한다.
검증 서비스에는 공개키 디렉터리만 읽기 전용으로 연결한다.
Docker 관리 권한자는 키에 접근할 수 있다. Compose secrets를 KMS/HSM과 같은 보호 수준으로 설명하지 않는다.

공개키는 비밀정보는 아니지만 무결성 보호가 필요하다. 임의 사용자가 검증키를 바꿀 수 없어야 한다.
CI는 각 빌드에 별도 키를 생성하고 공개키·개인키 전용 볼륨을 사용한다. Docker socket으로 연결된
호스트는 Jenkins 컨테이너의 workspace 경로를 공유하지 않기 때문에 bind mount를 쓰지 않는다.

### 정상 교체

1. 새 kid로 키를 생성한다. 기존 kid의 키 내용을 바꾸거나 덮어쓰지 않는다.
2. 기존 공개키와 새 공개키가 함께 있는 묶음을 모든 검증 인스턴스에 먼저 배포하고 재시작한다.
3. AccountService의 `JWT_SIGNING_KEY_ID`, 개인키 경로/secret source를 새 키로 바꾼다.
4. 기존·신규 Access와 Refresh 토큰을 검증한다. 프로세스별 공개키 버전이 섞이지 않았는지 확인한다.
5. 구키로 마지막 발행한 토큰의 최대 유효기간과 clock skew가 지난 뒤 구 공개키를 제거하고 재배포한다.
   현재 기본 Access 15분, Refresh 14일이므로 15분만 기다리면 안 된다.

최초 HS256 → RS256 전환에는 기존 토큰이 거절되므로 재로그인이 필요하다.
키 유출 시에는 유효기간을 기다리지 않는다. 해당 kid를 제거하고 **모든 검증 인스턴스**를 재시작하며,
영향받은 세션을 종료하고 재로그인을 유도한다. 토큰 자체에는 기밀성이 없으므로 개인정보를 최소화한다.

## Eureka 선택과 장애 경계

동적 인스턴스 등록과 Spring Cloud LoadBalancer 연동을 검증하기 위해 유지한다.
고정 Compose 환경의 서비스 DNS+프록시, Eureka, 컨테이너 오케스트레이터의 서비스 발견을 비교했을 때
기존 Spring 구조와 애플리케이션 단위 증설 실험에 가장 적은 변경으로 연결된다.
운영 비용은 heartbeat/캐시 지연, 단일 레지스트리 장애, 잘못된 인스턴스 등록, 추가 진단 경로다.

기존 장애는 Inventory의 단일 `@LoadBalanced RestClient.Builder`가 Eureka HTTP 통신까지 영향을
주면서 등록을 실패시킨 사례였다. 일반 `@Primary` Builder와 서비스 호출용 Builder를 분리했다.
컨테이너 TCP healthcheck만으로 Eureka 등록과 Gateway 라우팅을 검증할 수 없다는 근거다.

Eureka 중단 중 기존 캐시로 호출이 성공하는 것과 신규 인스턴스 발견 가능 여부는 별개다.
정상 종료와 SIGKILL도 다르다. 종료된 인스턴스를 캐시에서 제거하기 전 실패가 발생할 수 있다.
실험 결과에는 주입한 장애, 요청 실패율, 관측 기간, 재시작·회복 시간과 캐시 조건을 기록한다.

## Kafka 선택과 한계

현재 Account Outbox → Kafka → Audit의 장점은 DB 커밋과 감사 처리를 분리하고,
감사 소비자가 잠시 중단돼도 나중에 재처리할 수 있다는 점이다. 독립 consumer group은 각자의 offset을
가지며 동일 그룹 인스턴스는 파티션을 분담한다. 현재 실제 소비자는 하나이므로 다중 구독 서비스의
효과까지 실증했다고 표현하지 않는다.

이벤트 계약과 호환성은 `contracts/README.md`를 따른다. 현재 단일 브로커/복제 계수 1은
브로커 고가용성 구성이 아니다. Kafka 중단 실험은 Outbox와 소비자 복구 검증이다.
AccountService 자체를 여러 개로 증설할 때에는 스케줄러가 같은 Outbox 행을 선택하는 문제도
별도로 설계해야 한다. 이번 부하 실험은 ItemService를 증설하며 생산자 중복 가능성은 소비자
eventId 멱등성과 함께 명시한다.

## 측정·개선 선택

대규모 기능 추가, 전체 구조 재작성, 기존 흐름의 운영 검증을 비교해 마지막 방향을 선택했다.
품목 목록은 실제 존재하는 API이며 계정·상태 필터, 정렬, offset, 전체 건수 조회 비용을 함께 확인할 수 있다.
부하 분포는 운영 실측이 아닌 가설이다. 고정 데이터의 캐시 최상 조건과 혼합 요청을 구분하고,
개선 전후에는 데이터·요청 순서·CPU/메모리·요청률·기간을 고정한다.

후속 검토에서는 세 가지 보완을 적용했다: (1) 실험 명령의 프로젝트명·tmpfs DB 확인으로 기존 데이터 보호,
(2) 결정적 파라미터 생성으로 비교 재현성 확보, (3) replica별 DNS 서비스 발견과 메트릭으로 증설 관측 누락 방지.

추가 검토에서 관측 볼륨 이름의 상속 문제를 수정하고 시작·정리 전 접두사 검사를 추가했다.
Kafka 발행 대기가 지표 수집까지 막지 않도록 Account 스케줄러 풀을 2개로 설정했다.
Spring Boot의 기본 scheduler가 단일 스레드라는 공식 문서와 현재 두 scheduled 작업의 실행 경로를 근거로 한 보완이다.

## 참고한 공식 자료

- [Auth0 java-jwt RSA API](https://github.com/auth0/java-jwt)
- [Docker Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/)
- [Spring Cloud Netflix](https://docs.spring.io/spring-cloud-netflix/reference/spring-cloud-netflix.html)
- [Kafka design](https://kafka.apache.org/design/)
- [k6 parameterization](https://grafana.com/docs/k6/latest/examples/data-parameterization/)
- [MariaDB ANALYZE FORMAT=JSON](https://mariadb.com/docs/server/reference/sql-statements/administrative-sql-statements/analyze-and-explain-statements/analyze-format-json)
- [Java 21 memory diagnostics](https://docs.oracle.com/en/java/javase/21/troubleshoot/troubleshooting-memory-leaks.html)
- [Spring Boot task scheduling](https://docs.spring.io/spring-boot/reference/features/task-execution-and-scheduling.html)
