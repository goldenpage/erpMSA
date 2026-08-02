# ErpMSA

Eureka, Gateway, Account 서비스를 하나의 Git 저장소에서 관리하는 모노레포입니다.
각 서비스는 독립적인 Gradle 프로젝트이며 별도로 실행하고 배포합니다.

## 설정 관리 원칙

- `application.yml` 또는 `application.yaml`에는 비밀정보를 저장하지 않습니다.
- 공통 구조와 안전한 기본값만 Git으로 관리합니다.
- DB 비밀번호와 JWT 키 같은 비밀정보는 환경변수로 주입합니다.
- 실제 `.env` 파일은 Git에 올리지 않고 `.env.example`만 공유합니다.
- 운영 환경에서는 GitHub Actions Secrets나 별도의 Secret Manager를 사용합니다.

## 로컬 환경 설정

루트에서 예제 파일을 복사한 다음 빈 값을 채웁니다.

```bash
cp .env.example .env
```

JWT 키는 다음과 같이 생성할 수 있습니다.

```bash
openssl rand -base64 64 | tr -d '\n'
```

Spring Boot는 `.env`를 자동으로 읽지 않으므로, 실행할 터미널에서 환경변수로 내보냅니다.

```bash
set -a
source .env
set +a
```

각 서비스는 별도의 터미널에서 실행합니다.

```bash
./eurekaServer/gradlew -p eurekaServer bootRun
./gatewayServer/gradlew -p gatewayServer bootRun
./AccountService/gradlew -p AccountService bootRun
```

IntelliJ를 사용한다면 각 Run Configuration의 Environment variables에 같은 값을 설정할 수 있습니다.

## 운영 환경 주의사항

- `DB_PASSWORD`, `JWT_SECRET_BASE64`는 필수입니다.
- 운영에서는 `JPA_DDL_AUTO=validate`, `JPA_SHOW_SQL=false`를 사용합니다.
- HTTPS 환경에서는 `COOKIE_SECURE=true`를 사용합니다.
- 실제 자격증명을 Git 커밋이나 Docker 이미지에 포함하지 않습니다.
