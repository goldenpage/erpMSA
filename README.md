# ErpMSA

Eureka, Gateway, Account 서비스를 하나의 Git 저장소에서 관리하는 모노레포입니다.
각 서비스는 독립적인 Gradle 프로젝트이며 Docker Compose로 함께 실행하거나 별도로 배포합니다.
Prometheus가 서비스 메트릭을 수집하고 Grafana가 기본 모니터링 대시보드를 제공합니다.

## 설정 및 보안 관리 원칙

- `application.yml` 또는 `application.yaml`에는 비밀정보를 저장하지 않습니다.
- 공통 구조와 안전한 기본값만 Git으로 관리합니다.
- DB 비밀번호, JWT 키, Grafana 관리자 비밀번호는 환경변수로 주입합니다.
- 실제 `.env` 파일은 Git에 올리지 않고 `.env.example`만 공유합니다.
- CI에서는 Jenkins Credentials로 비밀정보를 주입합니다.
- 운영에서는 Vault, AWS Secrets Manager 등 별도의 Secret Manager 사용을 권장합니다.
- Jenkins 콘솔 로그에 비밀번호, 토큰, JWT 키가 출력되지 않도록 관리합니다.
- 비밀정보가 노출되면 로그만 삭제하지 않고 해당 자격증명을 즉시 폐기하거나 교체합니다.

## Docker Compose로 전체 실행

루트에서 예제 파일을 복사합니다.

```bash
cp .env.example .env
```

다음 명령으로 비밀값을 생성한 후 대응하는 `.env` 항목에 입력합니다. 각 항목에는 서로 다른 값을 사용합니다.

```bash
# JWT_SECRET_BASE64
openssl rand -base64 64 | tr -d '\n'

# GRAFANA_ADMIN_PASSWORD
openssl rand -base64 32 | tr -d '\n'

# GRAFANA_SECRET_KEY
openssl rand -hex 32
```

Docker Compose는 루트의 `.env`에서 값을 읽되 각 서비스에 필요한 환경변수만 전달합니다.

```bash
docker compose up -d --build --wait
```

상태와 로그를 확인합니다.

```bash
docker compose ps
docker compose logs -f
```

종료할 때는 데이터 볼륨을 유지합니다.

```bash
docker compose down
```

`docker compose down -v`는 MariaDB, Redis, Prometheus, Grafana 데이터를 삭제하므로 초기화가 필요한 경우에만 사용합니다.

## 로컬 접속 주소

- Gateway: `http://127.0.0.1:7070`
- AccountService: `http://127.0.0.1:7071`
- Eureka: `http://127.0.0.1:8761`
- Prometheus: `http://127.0.0.1:9090`
- Grafana: `http://127.0.0.1:3000`
- MariaDB: `127.0.0.1:3306`
- Redis: `127.0.0.1:3308`

컨테이너 내부에서는 Docker Compose 서비스 이름과 컨테이너 포트를 사용합니다.

## Prometheus와 Grafana

Prometheus는 15초마다 다음 엔드포인트를 수집합니다.

- `eureka-server:8761/actuator/prometheus`
- `account-service:7071/actuator/prometheus`
- `gateway-server:7070/actuator/prometheus`

Prometheus의 `Status > Target health` 화면에서 세 대상이 `UP`인지 확인할 수 있습니다.
Grafana에는 `ErpMSA/ErpMSA Spring Services` 대시보드가 자동으로 등록됩니다.
Grafana 로그인 정보는 `.env`의 `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`를 사용합니다.

Actuator와 모니터링 포트는 로컬 호스트에만 바인딩됩니다. 운영에서는 인터넷에 직접 공개하지 않고 사설 네트워크, 방화벽, TLS 및 접근 제어를 적용해야 합니다.

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

- `DB_PASSWORD`, `JWT_SECRET_BASE64`, `GRAFANA_ADMIN_PASSWORD`, `GRAFANA_SECRET_KEY`는 필수입니다.
- 운영에서는 `JPA_DDL_AUTO=validate`, `JPA_SHOW_SQL=false`를 사용합니다.
- HTTPS 환경에서는 `COOKIE_SECURE=true`, `GRAFANA_COOKIE_SECURE=true`를 사용합니다.
- 실제 자격증명을 Git 커밋, Docker 이미지, Jenkins 로그에 포함하지 않습니다.
- Grafana의 기본 SQLite 저장소는 로컬 개발용이며 고가용성 운영 환경에서는 PostgreSQL 또는 MySQL을 사용합니다.
- Prometheus 보존 기간과 볼륨 크기를 운영 트래픽에 맞게 설정합니다.
