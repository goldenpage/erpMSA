# FoodMaterials 목록 부하·장애 실험

이 도구는 Account 인증·Outbox 발행과 FoodMaterials 카탈로그를 대상으로 한다. 목표 업무 서비스의 명칭과 경로는
[서비스 설계 기준](../docs/service-architecture.md)을 따르며, 전환 후 데이터·API·검증 항목을 갱신해야 한다.

모든 명령은 저장소 루트에서 실행한다. `lab.py`는 고정 프로젝트 `erpmsa-sprint4-lab`과
전용 `.env`를 사용한다. DB 작업 전에 Compose label과 `/var/lib/mysql` tmpfs를 검사한다.
실제 ERP `.env`, 계정과 볼륨을 사용하지 않는다. 실험 종료 시 데이터를 제거한다.
선언된 볼륨 이름이 실험 프로젝트 접두사인지 시작·정리 전에 검사한다.
`python3 -m unittest discover -s performance -p 'test_*.py'`로 삭제 범위 보호 검사를 재실행할 수 있다.

## 재현

```bash
python3 performance/lab.py prepare
python3 performance/lab.py up
python3 performance/lab.py seed --rows 10000
python3 performance/lab.py run --label warmup --rate 20 --duration 20s
# 동일 애플리케이션에서 인덱스 하나만 바꿔 비교한다. 임시 DB에만 허용된다.
python3 performance/lab.py index --state baseline
python3 performance/lab.py sql --label baseline
python3 performance/lab.py run --label baseline-v2-gateway --rate 80 --duration 60s
python3 performance/lab.py run --label baseline-v2-direct --rate 80 --duration 60s --direct
python3 performance/lab.py index --state indexed
python3 performance/lab.py sql --label indexed
python3 performance/lab.py run --label indexed-gateway --rate 80 --duration 60s
python3 performance/lab.py run --label indexed-direct --rate 80 --duration 60s --direct
python3 performance/lab.py run --label final-one --rate 80 --duration 60s
python3 performance/lab.py scale --replicas 2
# Eureka 및 DNS/Prometheus에 새 인스턴스가 반영된 것을 확인한 뒤 실행
python3 performance/lab.py run --label scale-warmup --rate 20 --duration 30s
python3 performance/lab.py capture --label two-replicas
python3 performance/lab.py run --label final-two --rate 80 --duration 60s
python3 performance/smoke.py
# 각 장애 사이에는 모든 인스턴스의 정상 등록/호출을 확인한다.
python3 performance/lab.py kill-one --seconds 30
python3 performance/lab.py outage --service eureka-server --seconds 20
python3 performance/lab.py outage --service kafka --seconds 20
python3 performance/summarize.py
python3 performance/lab.py down
```

실험의 key·DB 암호는 prepare에서 생성된다. users.json에는 4시간 유효한 실험 전용 토큰이 있으므로
Git에 추가하지 않는다. 결과 폴더는 기본 ignore 대상이며, 공유 보고서에는 토큰 없는 통계만 옮긴다.
토큰이 만료되면 실험 환경을 재생성한다. 운영 세션 TTL은 변경하지 않는다.
`up`의 Docker 빌드 중에 부하를 측정하지 않는다. 부하 발생기도 같은 Docker VM의 자원을 사용한다.

## 데이터와 요청 가설

- 계정 6개, 각각 1만/1만/2만/2만/5만/10만 건: 총 21만 품목.
- ACTIVE 80%, INACTIVE 20%, 설명 200바이트, 계정 내 SKU 유일.
- 혼합 요청의 필터: ACTIVE 60%, INACTIVE 20%, 상태 미지정 20%를 목표로 결정적 해시 선택.
- 페이지 크기 20/50/100, 요청 약 65%는 첫 세 페이지, 나머지는 각 계정의 유효 페이지에 분산.
- 한 API와 값을 고정한 `--profile fixed`는 최상 캐시 조건 비교용이다. 사용자 트래픽 대표값으로 쓰지 않는다.
- 사용자 로그가 없으므로 이 비율은 가정이다. 실제 로그 확보 후 계정별 편중·페이지 분포를 갱신한다.

`constant-arrival-rate`는 응답이 느려져도 목표 요청률을 유지하려 한다. `dropped_iterations`를
함께 확인해야 하며, 요청률을 실제 처리량으로 바꿔 보고하지 않는다. 응답 상태뿐 아니라 fixture SKU로
계정 경계를 검사한다. 무작위 UUID를 매번 넣어 캐시를 강제로 무효화하지 않는다.

품목 API는 Page 계약 때문에 목록과 count 쿼리가 발생할 수 있다. `sql`은 상태별 첫/뒤쪽 페이지와
count를 각각 다섯 번 ANALYZE하여 실행계획·실제 읽은 행·시간을 저장한다. 같은 seed와 자원에서
개선 전후를 비교한다. 인덱스가 추가된 최신 코드만 실행하면 baseline 수치가 재현되는 것은 아니다.
baseline commit과 인덱스 조건은 보고서에 남긴다. `index`는 Flyway 이력을 수정하지 않는
임시 실험 조작이다. 실제 환경에서는 V2 migration으로 추가하며 수동 DROP을 실행하지 않는다.

`smoke.py`는 실험 계정을 추가하므로 부하 비교가 끝난 뒤 실행한다. Refresh 회전·로그아웃 후
재사용 거절, FoodMaterials 생성·조회·계정 경계, 5개 서비스의 501 계약, 제거된 경로의 404와 Outbox 발행을 검사한다.
감사 소비자·재고 동시성·DLT는 현재 구성의 검증 대상이 아니다. Kafka 복구 시간도 Outbox 발행 완료까지로 한정하며
소비자 처리까지 포함했던 과거 결과와 직접 비교하지 않는다.
장애 주입 전에는 Gateway의 Account·FoodMaterials 경로가 연속 10회 정상 응답하는지 확인한다.
Eureka 서버의 UP 등록만으로 Gateway 캐시까지 갱신됐다고 판단하지 않는다. 장애 영향이 겹친 실행은 별도로 표시한다.
`./scripts/verify-ci-key-transfer.sh`는 별도의 임시 볼륨에서 CI 키 전달/비루트 읽기 권한을 검사한 뒤 정리한다.

## 결과와 지표 해석

`results/<label>.json`: k6 지연 분포·오류율·처리량·누락 iteration.
`*-conditions.json`: 요청률/기간/경로/시각/프로세스 종료 상태.
`*-metrics.json`: Prometheus 쿼리, 컨테이너 상태·메모리 제한·CPU 제한, docker stats.
`*-sql.json`: 실제 SQL 실행계획 다섯 회 표본. 테스트 실패도 결과를 저장한 뒤 비정상 종료한다.

과거 Item 측정 파일과 새 결과를 섞지 않는다. `summarize.py`는 기본적으로 `results/summary.json`에 저장한다.

Grafana `ErpMSA Sprint 4 Diagnostics`는 인스턴스별 요청·지연, Hikari 연결/대기,
GC 이후 live data, GC 시간, Outbox 적체와 가장 오래된 이벤트 나이를 제공한다.
Outbox DB 조회 실패는 0으로 표시하지 않고 NaN과 sample_healthy=0으로 드러낸다.
지표 수집은 5초 주기로 DB를 조회하며 scrape 자체에서는 DB에 접근하지 않는다.
Account의 스케줄러 스레드를 2개로 설정해 Kafka 발행 대기 중에도 적체 지표를 갱신한다.

| 관측 | 가설 | 추가 증거와 대응 |
|---|---|---|
| DB 대기 증가와 지연 상승 | 쿼리/트랜잭션/연결 병목 | SQL plan·시간·연결 점유를 확인한 뒤 쿼리 개선 |
| GC 이후 live data 지속 증가 | 장기 보유·누수 가능성 | GC 로그, heap dump, 객체의 retained size/참조 확인 |
| heap 여유가 있는데 컨테이너 종료 | 네이티브 메모리·컨테이너 제한 등 | RSS·OOMKilled·종료 시각·memory limit·native memory 확인 |
| Outbox 나이 증가 | Kafka 발행 지연 | broker 상태·재시도·복구 후 Outbox 발행 완료 확인 |
| replica 증가에도 지연 개선 없음 | 공유 DB/게이트웨이/호스트 병목 | 전체 연결 수·DB CPU·Gateway 지표 확인 |

GC 로그는 컨테이너 stdout에 기록한다. JVM OOM 시 `/tmp`에 heap dump를 생성하도록 했지만,
OS가 SIGKILL한 경우 heap dump가 생성된다고 보장할 수 없다. 진단용 dump에는 민감정보가
포함될 수 있으므로 제한된 장소에 보관하고 공유하지 않는다. 원인 확인 전 heap 크기만 늘리지 않는다.
`kill-one`은 명시적 SIGKILL이다. exit 137을 메모리 부족 증거로 해석하지 않는다.

## 실험의 한계

단일 호스트 Compose 증설은 인스턴스 분배와 프로세스 장애 실험이다. 호스트 장애·다중 AZ·
단일 Kafka 브로커의 고가용성은 검증하지 않는다. 한 번의 짧은 부하는 장기 안정성·메모리 누수를
증명하지 못한다. 실제 목표 요청률과 p95 SLO는 운영 요구를 확보한 뒤 정한다.
기본 k6 gate는 HTTP 오류 1% 미만, 올바른 응답 99% 초과, dropped iteration 0이다.
이는 실험 판정 기준이며 운영 SLO라고 주장하지 않는다.
