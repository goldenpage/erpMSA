# ErpMSA

Eureka, Gateway, Account 서비스를 하나의 Git 저장소에서 관리하는 모노레포입니다.
각 서비스는 독립적인 Gradle 프로젝트이며 Docker Compose로 함께 실행하거나 별도로 배포합니다.

## 설정 관리 원칙

- `application.yml` 또는 `application.yaml`에는 비밀정보를 저장하지 않습니다.
- 공통 구조와 안전한 기본값만 Git으로 관리합니다.
- DB 비밀번호와 JWT 키 같은 비밀정보는 환경변수로 주입합니다.
- 실제 `.env` 파일은 Git에 올리지 않고 `.env.example`만 공유합니다.
- 운영 환경에서는 GitHub Actions Secrets나 별도의 Secret Manager를 사용합니다.

## Docker Compose로 전체 실행

루트에서 예제 파일을 복사한 다음 빈 값을 채웁니다.

```bash
cp .env.example .env
```

JWT 키는 다음과 같이 생성할 수 있습니다.

```bash
openssl rand -base64 64 | tr -d '\n'
```

Docker Compose는 루트의 `.env`에서 값을 읽되, 각 서비스에 필요한 환경변수만 선별해서 전달합니다. MariaDB와 Redis를 포함한 전체 서비스를 다음 명령으로 빌드하고 실행합니다.

```bash
docker compose up -d --build
```

상태와 로그를 확인합니다.

```bash
docker compose ps
docker compose logs -f
```

종료할 때는 데이터 볼륨을 유지하는 명령을 사용합니다.

```bash
docker compose down
```

`docker compose down -v`는 MariaDB와 Redis 데이터까지 삭제하므로 초기화가 필요한 경우에만 사용합니다.

로컬 접속 주소는 다음과 같습니다.

- Gateway: `http://127.0.0.1:7070`
- AccountService: `http://127.0.0.1:7071`
- Eureka: `http://127.0.0.1:8761`
- MariaDB: `127.0.0.1:3306`
- Redis: `127.0.0.1:3308`

컨테이너 내부에서는 MariaDB를 `mariadb:3306`, Redis를 `redis:6379`, Eureka를 `eureka-server:8761`로 연결합니다.

## Gradle로 개별 실행

특정 서비스를 IDE나 Gradle로 실행할 때는 먼저 환경변수를 현재 터미널로 내보냅니다.

```bash
set -a
source .env
set +a
```

```bash
./eurekaServer/gradlew -p eurekaServer bootRun
./gatewayServer/gradlew -p gatewayServer bootRun
./AccountService/gradlew -p AccountService bootRun
```

## 운영 환경 주의사항

- `DB_PASSWORD`, `JWT_SECRET_BASE64`는 필수입니다.
- 운영에서는 `JPA_DDL_AUTO=validate`, `JPA_SHOW_SQL=false`를 사용합니다.
- HTTPS 환경에서는 `COOKIE_SECURE=true`를 사용합니다.
- 실제 자격증명을 Git 커밋이나 Docker 이미지에 포함하지 않습니다.
