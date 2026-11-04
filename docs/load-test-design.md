# 대규모 부하 테스트 설계 및 사전 분석

> 상태: **설계 문서이며 실행 결과가 아니다.** 아래 병목 분석은 코드·설정을 읽고 세운 가설이며 측정으로 확인해야 한다.
> 기준 커밋: `6268d9c` · 작성일: 2026-11-04 · 실행 주체: 사용자 (클라우드 또는 전용 장비)
>
> 4차 스프린트의 Item/Inventory 측정값([sprint4-results.md](sprint4-results.md))은 비교 기준으로 쓰지 않는다.
> 새 결과는 현재 7개 서비스 구조와 현재 이미지로 다시 측정한 값만 기록한다.

## 1. 이 테스트로 답할 질문

| ID | 질문 | 판정에 필요한 결과 |
|---|---|---|
| Q1 | 읽기·쓰기·혼합 부하에서 시스템이 버티는 최대 요청률(포화점)은 얼마인가 | 단계별 요청률·오류율·p95·누락 iteration |
| Q2 | 포화점에서 **가장 먼저 막히는 자원**은 무엇인가 | 서비스별 CPU, Hikari 대기, 스레드, DB 잠금 대기 |
| Q3 | 병목 서비스를 증설하면 처리량이 실제로 늘어나는가 | 인스턴스 1/2/3개의 포화점 비교 |
| Q4 | 과부하·하류 지연·인스턴스 장애 중에도 **폐기 재고 정합성**이 유지되는가 | §7의 불변식 I1~I5 |
| Q5 | 장시간 부하에서 지연·메모리·데이터 증가에 따른 성능 저하가 있는가 | 소크 구간의 p95 추세, GC 이후 live data, PENDING 누적 |

Q4는 다른 질문보다 우선한다. 처리량이 높아도 중복 차감이나 근거 없는 완료 처리가 하나라도 나오면 그 실행은 실패로 판정한다.

## 2. 코드 기반 병목 분석

### 2.1 요청 경로별 자원

| 경로 | 거치는 자원 | 비고 |
|---|---|---|
| `GET /foodmaterials` | Gateway(가상 스레드, JWT 검증) → FoodMaterials(가상 스레드, JWT 검증) → itemdb 풀 10 | Page 계약 때문에 목록 쿼리와 count 쿼리가 함께 실행됨 |
| `GET /foodmaterials/inventories…` | Gateway → FoodMaterials → inventorydb 풀 10 | |
| `GET /menus` | Gateway → Menus(Tomcat 플랫폼 스레드) → menusdb 풀 10 | 목록 + count |
| `GET /disposals` | Gateway → Disposals(Tomcat 플랫폼 스레드) → disposalsdb 풀 10 | 목록 + count. **쓰기 경로와 같은 풀을 사용** |
| `POST /disposals` | Gateway → Disposals: 등록 트랜잭션 → 잠금 트랜잭션 안에서 FoodMaterials 동기 HTTP 호출 → FoodMaterials inventorydb 잠금·원장 저장 | JWT 검증 3회, DB 트랜잭션 3개, 행 잠금 2개 |
| `POST /account/auth/login` | Gateway(검증 생략) → Account: BCrypt(기본 cost 10) + RS256 서명 + Redis/DB | CPU 비용이 큰 경로로 추정. 다른 경로와 섞지 않는다 |

모든 업무 DB(mydb, itemdb, inventorydb, menusdb, disposalsdb)는 **같은 MariaDB 인스턴스 하나**를 쓴다(`compose.yaml`).
서비스를 증설해도 DB는 공유 자원으로 남는다.

### 2.2 폐기 경로의 연쇄 지연 위험 (가장 중요)

`DisposalStore.process()`(`DisposalsService/.../disposal/DisposalStore.java:39`)는 다음 순서로 동작한다.

1. disposalsdb 연결을 얻고 폐기 행을 `PESSIMISTIC_WRITE`로 잠근다.
2. 잠금과 연결을 쥔 채 FoodMaterials를 동기 HTTP로 호출한다(연결 2초, 읽기 3초, `StockClientConfiguration.java:14-15`).
3. 결과를 저장하고 커밋한다.

이 구조에서는 **연결 하나가 대략 FoodMaterials 응답시간만큼 점유된다.** Little의 법칙으로 Disposals 인스턴스 하나의 처리 상한을 추정하면 다음과 같다.

```
최대 처리량 ≈ 풀 크기 / 연결 점유 시간
            ≈ 10 / (FoodMaterials 응답시간 + 로컬 SQL·커밋 시간)
```

| FoodMaterials 응답시간(가정) | Disposals 인스턴스당 상한(추정) |
|---:|---:|
| 10 ms | 약 700~900 req/s |
| 100 ms | 약 90~100 req/s |
| 1 s | 약 10 req/s |
| 3 s(읽기 제한) | 약 3 req/s |

등록 트랜잭션(`register`)도 같은 풀에서 연결을 짧게 쓴다. 수치는 계산 예시일 뿐이므로 E1·E3에서 측정해 확인한다.

여기서 생기는 추가 위험은 다음과 같다.

- **스레드 대기**: Disposals는 Tomcat 플랫폼 스레드(기본 최대 200개)를 쓰고 풀은 10개다. 포화 시 최대 190개 스레드가 Hikari의 기본 연결 대기 시간(30초) 동안 대기할 수 있다. Disposals는 Hikari 설정을 따로 두지 않았다.
- **읽기까지 번짐**: `GET /disposals`도 같은 풀을 쓰므로 쓰기 경로의 하류 지연 때문에 조회까지 느려질 수 있다.
- **제한 시간 불일치**: Disposals는 3초 뒤 포기하지만, FoodMaterials 내부는 Hikari 연결 대기(기본 30초)와 InnoDB 잠금 대기(MariaDB 기본 50초)가 더 길다. 따라서 과부하에서는 **FoodMaterials는 나중에 차감을 커밋했는데 Disposals는 PENDING인 상태**(이하 `D-P`)가 늘어날 수 있다.
  설계상 허용된 상태이고 같은 명령 ID로 재시도하면 복구되지만, 부하 테스트에서는 그 건수를 반드시 따로 센다.
- **재시도 폭주**: 과부하 중 PENDING을 즉시 재시도하면 같은 병목에 요청을 더 쌓게 된다. 재시도 일괄 처리는 부하 구간이 끝난 뒤 요청률을 제한해서 실행한다.

중복 차감 방어는 코드상 두 겹이다. FoodMaterials가 재고 행을 잠근 뒤 같은 `DISPOSAL-{id}` 원장을 먼저 조회하고, `uk_movement_account_request` 유일 제약이 있다. 부하 중 이 방어가 유지되는지가 Q4의 핵심이다.

### 2.3 같은 재고 행에 요청이 몰릴 때

`InventoryRepository.lockOwned`는 `(account_id, item_id)` 재고 행을 비관적 잠금으로 잡는다. 같은 식자재에 대한 폐기는 완전히 차례로 처리된다.

```
핫 재고 1건의 처리 상한 ≈ 1 / 재고 잠금 유지 시간(잠금 SELECT + 원장 조회 + UPDATE + INSERT + 커밋)
```

VU를 늘려도 처리량은 일정 수준에서 멈추고 지연만 VU 수에 비례해 늘어날 것으로 예상한다(H3).
실험실 DB가 tmpfs이면 커밋의 fsync 비용이 거의 없어 이 상한을 **실제보다 높게** 측정하게 된다(§2.7).

### 2.4 DB 연결 예산

| 서비스 | 인스턴스당 풀 | 근거 |
|---|---:|---|
| Account | 10 | `hikari.maximum-pool-size: 10` |
| FoodMaterials | 10 (itemdb) + 10 (inventorydb) | itemdb는 기본값, 재고는 `FOOD_MATERIAL_INVENTORY_DB_POOL_SIZE:10` |
| Menus | 10 | Hikari 기본값 |
| Disposals | 10 | Hikari 기본값 |
| Notices·Bills·Purchase | 0 | DB 없음 |
| **서비스 묶음 1세트** | **50** | |

MariaDB 기본 `max_connections`는 151이다. 업무 서비스를 모두 3개씩 띄우면 150개라서 관리 연결과 exporter가 들어갈 여유가 없다.
DB는 실험 구성상 2 CPU이므로 **연결 수를 늘리는 것이 처리량 증가로 이어진다는 보장도 없다.** 증설 실험(E4)은 연결 총합을 표로 기록한다.
`max_connections`를 바꾸는 실행은 별도 조건으로 표시한다.

### 2.5 스레드 모델 차이

- Gateway와 FoodMaterials는 가상 스레드를 쓴다. 스레드 수로 압력을 조절하지 않으므로 대기열이 Hikari 풀 앞에 생긴다.
- Account, Menus, Disposals는 Tomcat 플랫폼 스레드를 쓴다. 스레드 고갈과 풀 대기가 함께 나타날 수 있다.
- 포화 증상을 서비스별로 다르게 읽어야 한다. FoodMaterials는 `hikaricp_connections_pending`을, Disposals·Menus는 스레드 사용량과 풀 대기를 함께 본다.

### 2.6 인증 비용

RS256 검증은 Gateway와 각 서비스 필터에서 각각 실행된다. 조회 한 번에 2회, 폐기 한 번에 3회다(Gateway, Disposals, FoodMaterials).
검증 비용은 요청당 작을 것으로 보지만, Gateway가 1 CPU인 실험 구성에서는 E0에서 따로 측정한다.
로그인은 BCrypt 때문에 비용이 훨씬 크다. 테스트 토큰은 측정 전에 미리 발급하고 로그인 부하는 별도 실험으로만 다룬다.

### 2.7 데이터 증가와 저장소 조건

- `disposal.id`는 `UUID.randomUUID()` 문자열(VARCHAR 36)이 기본키다. 무작위 삽입으로 클러스터드 인덱스에 페이지 분할이 생기고, 보조 인덱스마다 36바이트 기본키가 붙는다. 행이 수백만 건 이상이면 쓰기·버퍼 풀 비용이 커질 수 있다(H6).
- `stock_movement`는 폐기 1건마다 1행씩 늘어난다. `inventory.updated_at` 인덱스도 폐기마다 갱신된다.
- 목록 API는 모두 count 쿼리를 실행한다. 계정별 데이터가 늘면 count 비용도 함께 늘어난다.
- MariaDB 기본 `innodb_buffer_pool_size`는 128 MiB다. 실험 DB는 별도 설정이 없으므로 대량 데이터에서는 버퍼 풀이 결과를 좌우한다. **DB 설정을 명시하고 결과에 함께 기록한다.**
- 현재 실험실의 MariaDB는 tmpfs(`compose.performance.yaml`)다. 기존 볼륨을 보호하는 데는 좋지만 fsync 비용이 빠져 쓰기 지연이 실제보다 낙관적으로 나온다.
  쓰기 경로의 대규모 측정은 **실험 접두사가 붙은 전용 디스크 볼륨**을 쓰는 조건을 추가하고, `innodb_flush_log_at_trx_commit` 값을 기록한다. 기존 볼륨은 사용하지 않는다.

### 2.8 관측 공백

| 공백 | 영향 | 보완 |
|---|---|---|
| Disposals→FoodMaterials 호출 지표 없음. `RestClient.builder()`를 직접 만들어 Spring의 관측 설정이 적용되지 않는 것으로 보인다(실행 시 확인) | 하류 지연과 Disposals 지연을 분리할 수 없음 | `ObservationRegistry` 연결 또는 클라이언트 타이머 추가 |
| PENDING 건수 지표 없음 | 과부하 중 PENDING 누적을 실시간으로 볼 수 없음 | Outbox 지표와 같은 방식의 주기적 DB 집계 게이지 |
| MariaDB exporter 없음 | 잠금 대기, 실행 중 스레드, 버퍼 풀 적중률을 볼 수 없음 | 실험 구성에만 mysqld_exporter 추가 |
| 호스트·컨테이너 지표 없음(`lab.py capture`의 docker stats 스냅샷만 있음) | 시간에 따른 CPU 포화 확인 불가 | 실험 구성에 node_exporter·cAdvisor 추가 |
| k6 지표가 Prometheus에 없음 | 부하와 서버 지표를 같은 시간축으로 볼 수 없음 | k6 `experimental-prometheus-rw` 출력 |
| Prometheus 수집 주기 15초 | 스파이크 실험의 해상도 부족 | 실험 구성만 5초로 변경 |
| Tomcat 스레드 지표 | 플랫폼 스레드 서비스의 고갈 확인 필요 | 노출 여부를 E0에서 확인하고 필요하면 실험 구성에서 활성화 |

## 3. 환경 설계

### 3.1 원칙

- **부하 발생기와 대상 시스템을 다른 호스트에 둔다.** 같은 호스트에서 측정한 결과는 대규모 결과로 보고하지 않는다.
- 부하 발생기 CPU가 70%를 넘었거나 `dropped_iterations`가 0이 아니면 그 단계는 무효다. 발생기를 늘려 다시 측정한다.
- 기존 원칙을 유지한다. 전용 프로젝트·전용 데이터·실험 접두사 볼륨만 사용하고 실제 DB와 기존 볼륨에는 접근하지 않는다.
- 모든 호스트의 시계를 동기화(NTP)하고 같은 리전·같은 존에 둔다. 존을 넘는 지연은 별도 조건이다.

### 3.2 구성 단계

| 단계 | 구성 | 목적 |
|---|---|---|
| T1 | 대상 VM 1대(서비스 전체 + DB) + 부하 VM 1대 | 도구·스크립트·불변식 검사 보정. 소규모 포화점 |
| T2 | 앱 VM 1대 + **DB 전용 VM 1대(디스크 볼륨)** + 부하 VM 1~N대 | 본 측정. DB와 앱의 CPU를 분리해 병목을 구분 |
| T3 (선택) | 앱 VM 2대 이상 + DB VM + 부하 VM N대 | 다중 호스트 증설. 단일 Eureka·단일 브로커 한계는 그대로임 |

T1에서 모든 실험을 짧게 한 번씩 돌려 스크립트와 판정이 맞는지 확인한 뒤 T2로 간다.
현재 `compose.performance.yaml`의 CPU·메모리 제한(Gateway·FoodMaterials·Disposals 1 CPU, DB 2 CPU 1.5 GiB)은 **환경변수로 바꿀 수 있게** 고친다.
제한값은 모든 결과에 기록한다.

### 3.3 부하 발생기

- k6를 쓴다(기존 스크립트·`grafana/k6:1.7.1`과 일치).
- 처리량 측정은 **개방 모델**(`constant-arrival-rate`, `ramping-arrival-rate`)을 쓴다. 응답이 느려져도 요청 도착률이 유지되어 포화를 숨기지 않는다.
- 핫 재고 실험은 **폐쇄 모델**(`constant-vus`)을 쓴다. 동시 경쟁 수를 직접 통제하기 위해서다.
- `maxVUs`는 `목표 RPS × 예상 p99(초) × 2` 이상으로 둔다. 현재 고정값 150은 대규모에서 부족하다.
- 여러 발생기는 `--execution-segment`로 부하를 나눈다. 각 발생기는 서로 겹치지 않는 requestId 접두사를 쓴다.

## 4. 데이터와 토큰

### 4.1 규모 가설

실제 매장 수·식자재 수 자료가 없으므로 아래는 **가설**이다. 운영 자료가 생기면 바꾼다.
계정은 매장 하나로 보고, 소·중·대 매장으로 나눠 데이터와 트래픽을 편중시킨다.

| 매장 등급 | 계정 비율 | 식자재 수 | 재고 행 | 요청 가중치 |
|---|---:|---:|---:|---:|
| 소 | 70% | 200 | 식자재와 같음 | 1 |
| 중 | 25% | 1,000 | 식자재와 같음 | 3 |
| 대 | 5% | 5,000 | 식자재와 같음 | 10 |

| 규모 | 계정 | 식자재·재고 행 | 메뉴 | 사전 원장 | 사전 폐기 |
|---|---:|---:|---:|---:|---:|
| D1 (T1 보정) | 100 | 약 6.4만 | 계정당 50 | 50만 | 10만 |
| D2 (본 측정) | 1,000 | 약 64만 | 계정당 50 | 500만 | 100만 |
| D3 (선택) | 5,000 | 약 320만 | 계정당 50 | 2,500만 | 500만 |

- 계정·토큰은 API로 만들고, 식자재·재고·사전 원장·사전 폐기 행은 SQL로 대량 생성한다(기존 `seed`와 같은 방식).
- 재고 초기 수량은 예상 폐기량의 1.5배 이상으로 둔다. 그렇지 않으면 재고 부족 409 경로만 측정하게 된다.
  사전 원장은 재고별 수량 합이 `on_hand_quantity`와 맞도록 생성한다(I1 검사가 사전 데이터에서도 성립해야 한다).
- 데이터셋 생성 매개변수와 생성 후 행 수·체크섬을 `dataset.json`에 기록한다. 같은 데이터셋끼리만 비교한다.

### 4.2 토큰

- 측정 전에 계정마다 Access Token을 미리 발급한다. 로그인 비용을 측정 구간에 섞지 않는다.
- 실험실 Access TTL은 4시간이다(`lab.py prepare`의 `JWT_ACCESS_TTL`). 실행 직전에 남은 만료 시간이 `실행 시간 + 30분`보다 긴지 확인한다.
- 토큰 파일은 Git에 넣지 않고 권한 0600으로 둔다. 운영 TTL은 바꾸지 않는다.

## 5. 워크로드 모델

트래픽 로그가 없으므로 비율은 **가설**이다. 비율이 결과에 얼마나 영향을 주는지 보기 위해 W-MIX는 쓰기 비율을 바꾼 변형도 측정한다.

| 워크로드 | 구성 | 용도 |
|---|---|---|
| W-READ | `GET /foodmaterials` 35%, `GET /foodmaterials/inventories` 20%, `GET /foodmaterials/inventories/{id}` 15%, `GET /menus` 15%, `GET /disposals` 10%, `GET /account/auth/me` 5% | 읽기 포화점 |
| W-WRITE | `POST /disposals` 100% (수량 1, 매장 가중치에 따라 식자재 선택) | 폐기 경로 포화점, §2.2 검증 |
| W-MIX | W-READ 90% + W-WRITE 10% (변형: 쓰기 5%, 20%) | 대표 혼합 가설 |
| W-AUTH | `POST /account/auth/login` 100% | 로그인 몰림. 다른 실험과 분리 |
| W-BASE | `GET /notices` (인증된 501 응답) | Gateway·JWT·발견 오버헤드 보정 전용. Notices 기능 측정이 아님 |

요청 생성 규칙은 다음과 같다.

- 목록 페이지 분포는 기존 `foodmaterials.js`의 결정적 해시 방식을 그대로 쓴다. 약 65%는 앞쪽 세 페이지, 나머지는 유효한 뒤쪽 페이지다.
- 폐기 requestId: `LT-{runId}-{발생기}-{iteration}`. 실행 간·발생기 간에 겹치지 않는다.
- **재전송 주입**: W-WRITE iteration의 5%는 직전에 보낸 같은 requestId·같은 본문을 다시 보낸다. 기대 결과는 첫 요청과 같은 결과, 추가 차감 0이다.
- **충돌 주입**: 1%는 같은 requestId에 다른 수량을 보낸다. 기대 결과는 409이며 차감 0이다.
- 응답은 200 / 202 / 409 / 기타로 태그를 나눠 집계한다. **202는 성공으로 세지 않는다.**
- 무작위 값으로 캐시를 일부러 깨지 않는다.

## 6. 실험 매트릭스

모든 실험의 첫 60초는 워밍업으로 보고 판정에서 제외한다. 본 측정은 각 조건을 최소 3회 반복하고 중앙값과 범위를 보고한다.

| ID | 실험 | 방법 | 확인할 것 |
|---|---|---|---|
| E0 | 보정 | W-BASE와 W-READ를 낮은 요청률에서 5분. 발생기 CPU, Gateway 단독 지연, 지표 노출 여부 확인 | 발생기가 목표 요청률을 낼 수 있는가, 지표 공백(§2.8)이 메워졌는가 |
| E1 | 단계 포화 | `ramping-arrival-rate`: 50 RPS부터 1.5배씩, 단계마다 3분. W-READ, W-WRITE, W-MIX 각각 | 포화점(§7.1), 첫 병목 자원 |
| E2 | 핫 재고 | `constant-vus` 1/5/10/25/50/100, 단계마다 2분. 재고 1건, 이어서 10건 | 처리량 정체 수준, 지연이 VU에 비례하는지, InnoDB 잠금 대기 |
| E3 | 하류 지연 | W-WRITE를 E1 포화점의 50%로 유지하면서 FoodMaterials에 지연 +50ms / +500ms / +2.5s / +4s 주입(tc netem 또는 `docker update --cpus`) | Disposals 풀 대기, 202 비율, `D-P` 건수, `GET /disposals`로 번지는지 |
| E4 | 증설 | E1에서 확인한 병목 서비스를 1→2→3개로 늘리고 E1을 반복. 늘린 뒤 Gateway 경로 10회 연속 정상과 60초 이상의 안정화 확인 | 포화점 증가율 `knee(n) / (n × knee(1))`, DB 연결 총합 |
| E5 | 스파이크 | 포화점의 20%에서 10초 안에 150%로 올리고 2분 유지한 뒤 20%로 복귀 | 오류 폭, 복귀 후 p95가 기준으로 돌아오는 시간, PENDING 증가 |
| E6 | 소크 | W-MIX를 포화점의 60~70%로 2시간 | p95 추세(처음 15분과 마지막 15분), GC 이후 live data 기울기, 풀 대기, 테이블 증가 |
| E7 | 부하 중 장애 | W-MIX 50% 부하에서 FoodMaterials 2개 중 1개 SIGKILL, 이어서 Disposals 1개 SIGKILL | 오류·202·`D-P` 건수, 복구 후 재시도 일괄 처리 뒤 불변식 |
| E8 | 로그인 몰림 | W-AUTH 단계 포화. 다른 실험과 분리된 데이터셋에서 실행 | Account CPU 포화점, Redis·DB 부하 |

E3과 E7은 실험마다 끝난 뒤 다음 순서를 지킨다. 부하 중단 → 장애 해제·안정화 → 요청률을 제한한 재시도 일괄 처리(예: 초당 20건) → 불변식 검사.

## 7. 판정 기준

### 7.1 단계 포화 판정

다음 중 하나라도 해당하면 그 단계를 "포화"로 본다. **포화점**은 포화가 아닌 마지막 단계의 요청률이다.

- HTTP 오류율 1% 이상(409·202는 오류율과 따로 집계)
- p95가 E0 기준 p95의 3배 초과
- 해당 단계의 `dropped_iterations` > 0 (발생기 문제가 아닌 것이 확인된 경우)
- 실제 처리량이 목표 요청률의 95% 미만
- W-WRITE에서 202 비율 1% 이상

이 기준은 실험 판정용이며 운영 SLO가 아니다. 운영 목표(예: 요청률과 p95)가 정해지면 그 기준을 별도로 판정한다.

### 7.2 폐기 정합성 불변식

실험실에서는 모든 업무 DB가 같은 MariaDB에 있어 DB를 가로지르는 조회로 검사할 수 있다. 이는 실험실 검증 수단일 뿐 서비스 간 결합을 뜻하지 않는다.
모든 검사의 기대값은 0건이다(I5는 분류만 한다).

```sql
-- I1 재고 보존: 현재고 = 원장 증감 합 (INITIAL 원장의 증감은 초기 수량)
SELECT i.id FROM inventorydb.inventory i
JOIN (SELECT inventory_id, SUM(quantity_delta) s FROM inventorydb.stock_movement GROUP BY inventory_id) m
  ON m.inventory_id = i.id
WHERE i.on_hand_quantity <> m.s;

-- I2 COMPLETED ↔ 원장 1:1
SELECT d.id FROM disposalsdb.disposal d
LEFT JOIN inventorydb.stock_movement m
  ON m.account_id = d.account_id AND m.request_id = CONCAT('DISPOSAL-', d.id)
WHERE d.status = 'COMPLETED'
  AND (m.id IS NULL OR m.id <> d.movement_id OR m.quantity_delta <> -d.quantity OR m.movement_type <> 'DISPOSAL');

-- I3 대응하는 폐기 기록이 없는 폐기 원장
SELECT m.id FROM inventorydb.stock_movement m
LEFT JOIN disposalsdb.disposal d
  ON m.account_id = d.account_id AND m.request_id = CONCAT('DISPOSAL-', d.id)
WHERE m.movement_type = 'DISPOSAL' AND d.id IS NULL;

-- I4 REJECTED인데 차감된 기록
SELECT d.id FROM disposalsdb.disposal d
JOIN inventorydb.stock_movement m
  ON m.account_id = d.account_id AND m.request_id = CONCAT('DISPOSAL-', d.id)
WHERE d.status = 'REJECTED';

-- I5 PENDING 분류 (재시도 일괄 처리 전후에 각각 기록)
SELECT IF(m.id IS NULL, 'PENDING_NOT_APPLIED', 'PENDING_APPLIED_D-P') kind, COUNT(*)
FROM disposalsdb.disposal d
LEFT JOIN inventorydb.stock_movement m
  ON m.account_id = d.account_id AND m.request_id = CONCAT('DISPOSAL-', d.id)
WHERE d.status = 'PENDING' GROUP BY kind;
```

추가로 클라이언트 관측과 DB를 대조한다.

- k6가 받은 200 응답의 disposalId는 모두 DB에서 COMPLETED여야 한다.
- 재전송 주입 요청이 첫 요청과 다른 확정 결과를 받으면 실패다.
- 충돌 주입 요청이 200을 받으면 실패다.
- 재시도 일괄 처리 뒤 남은 PENDING은 0이거나, 건마다 원인(예: 재고 없음 확인 불가)을 기록한다. PENDING을 수동으로 완료 처리하거나 DB를 보정하지 않는다.

## 8. 수집할 지표

| 계층 | 지표 |
|---|---|
| 부하 발생기 | 요청률, 상태별 건수(200/202/409/기타), 지연 분포(p50/p95/p99/max), `dropped_iterations`, 발생기 CPU |
| Gateway·서비스 | `http_server_requests` 히스토그램(경로·상태별), JVM CPU, GC 일시정지, GC 이후 live data, 스레드 |
| 연결 풀 | 풀별 `hikaricp_connections_active/pending/timeout`, 연결 획득 시간 |
| 하류 호출 | Disposals→FoodMaterials 호출 지연·결과(보완 후) |
| 업무 상태 | PENDING 건수 게이지(보완 후), Outbox 적체·나이(기존) |
| DB | Threads_running, `Innodb_row_lock_waits/time`, 버퍼 풀 적중률, 디스크 IOPS·지연, 슬로 쿼리 |
| 호스트·컨테이너 | CPU(스로틀 포함), 메모리·RSS, 네트워크, 디스크 |

## 9. 분석 방법

1. **병목 찾기**: 포화 단계에서 자원마다 사용률·포화도·오류를 본다(USE). 서비스마다 요청률·오류·지연을 본다(RED).
   예: CPU가 70% 미만인데 `hikaricp_connections_pending`이 계속 0보다 크면 연결 풀 병목이다. CPU가 90% 이상이면 계산 병목이다.
2. **Little의 법칙 대조**: `동시 처리 중 요청 ≈ 처리량 × 평균 지연`을 계산해 풀 크기·스레드 수와 비교한다. §2.2의 추정이 맞는지 확인한다.
3. **지연 분해**: Gateway 지연 − 서비스 지연 = Gateway 구간. Disposals 지연 − 하류 호출 지연 = Disposals 내부 구간.
4. **증설 효율**: E4의 `knee(n) / (n × knee(1))`가 0.7 미만이면 공유 자원(DB, Gateway, 호스트) 병목을 먼저 의심한다.
5. **반복성**: 3회 결과의 범위가 중앙값의 ±10%를 넘으면 원인(콜드스타트, 노이즈 이웃, 발생기 부족)을 확인하기 전에는 결론을 내리지 않는다.
6. **기록**: 실행마다 Git SHA, 이미지 digest, 데이터셋 체크섬, CPU·메모리 제한, 풀 크기, DB 설정, 호스트 사양, k6 버전과 발생기 수를 남긴다.

### 9.1 검증할 가설

| ID | 가설 | 맞다면 보일 증거 | 틀렸다면 |
|---|---|---|---|
| H1 | W-WRITE의 첫 병목은 CPU가 아니라 Disposals 연결 풀(10)이다 | 포화 시 Disposals CPU < 70%, pending > 0, 하류 호출 지연은 정상 | FoodMaterials 재고 풀 또는 DB 잠금 대기를 확인 |
| H2 | FoodMaterials 지연이 약 3초를 넘으면 202와 `D-P`가 급증하고 `GET /disposals`도 느려진다 | E3의 +4s 조건에서 202 증가, I5의 D-P > 0, 조회 p95 상승 | 타임아웃 경로를 로그로 확인 |
| H3 | 핫 재고는 VU와 무관한 처리량 상한이 있고 지연은 VU에 비례한다 | E2 처리량 정체, `Innodb_row_lock_time` 증가 | 잠금 외 병목 확인 |
| H4 | W-READ의 첫 병목은 Gateway(1 CPU) 또는 DB(2 CPU)다 | 둘 중 하나의 CPU가 먼저 90% 이상 | 서비스 풀 또는 count 쿼리를 확인 |
| H5 | 단일 MariaDB 때문에 앱 증설 효율이 2개 이후 급격히 떨어진다 | E4 효율 < 0.7, DB CPU 포화 | 앱 쪽 병목이 남아 있다는 뜻 |
| H6 | 소크·대규모 데이터에서 `disposal` 무작위 UUID 기본키와 count 쿼리 때문에 폐기 쓰기·목록 p95가 점점 오른다 | E6에서 p95 상승, 버퍼 풀 적중률 하락 | 해당 원인 제외 |

가설이 맞더라도 이번 테스트에서 제품 코드를 바로 고치지 않는다. 결과를 근거로 개선 후보(풀 분리, 호출 제한 시간, 기본키 방식, 페이지 계약 등)를 따로 검토한다.

## 10. 실행 전 구현 작업

| 우선 | 작업 | 위치 |
|---|---|---|
| P0 | CPU·메모리 제한, 풀 크기, 인스턴스 수, DB 설정(`max_connections`, 버퍼 풀, 디스크/tmpfs)을 환경변수로 조절 | `compose.performance.yaml`, `performance/lab.py` |
| P0 | 실험용 mysqld_exporter, node_exporter, cAdvisor, Prometheus 5초 수집, k6 remote write | 실험 구성만 |
| P0 | D1~D3 데이터 생성(매장 등급, 재고, 사전 원장·폐기, 메뉴)과 토큰 미리 발급 | `performance/lab.py seed` 확장 |
| P0 | k6 스크립트: W-READ/W-WRITE/W-MIX/W-AUTH/W-BASE, 핫 재고, 재전송·충돌 주입, 상태별 태그 | `performance/*.js` |
| P0 | 불변식 I1~I5 검사기와 요청률 제한 재시도 일괄 처리기 | `performance/` 새 스크립트 |
| P1 | Disposals 하류 호출 지표와 PENDING 게이지 (관측 전용 제품 코드 변경. 사용자 승인 후) | `DisposalsService` |
| P1 | 하류 지연·CPU 제한 주입 명령 | `performance/lab.py` |
| P2 | 포화점 자동 판정, 증설 효율 계산, 반복 결과 요약 | `performance/summarize.py` |

## 11. 범위 밖과 한계

- Notices·Bills·Purchase 업무 기능은 501 상태이므로 측정하지 않는다. W-BASE는 오버헤드 보정 용도로만 쓴다.
- 단일 Eureka·단일 Kafka 브로커·단일 MariaDB의 고가용성은 이 테스트로 증명하지 않는다.
- 워크로드 비율과 데이터 규모는 가설이다. 결과를 "실사용 대표값"으로 보고하지 않는다.
- 결과는 측정한 하드웨어·설정에서의 값이다. 다른 환경의 용량으로 옮겨 쓰지 않는다.
- 실제 DB, 기존 볼륨, 기존 `.env`는 사용하지 않는다.

## 12. 결정이 필요한 사항

1. 실행 환경과 호스트 사양(T2의 앱·DB·부하 VM 크기, 클라우드 종류)
2. 운영 목표가 있는지(예: 목표 요청률과 p95). 없으면 포화점과 병목 확인을 목표로 한다.
3. 본 측정 데이터 규모(D2 또는 D3)
4. P1의 관측 전용 제품 코드 변경(Disposals 지표) 허용 여부
5. 풀 크기·DB 설정 튜닝 실험을 이번 범위에 넣을지. 넣는다면 기준선 측정과 분리해 별도 조건으로 기록한다.
