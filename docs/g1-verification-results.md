# G1 격리 검증 실행 기록

> 범위: 정상 흐름 설계의 첫 구현 단계인 격리 환경·G1만 해당한다.
> Codex 구현 / 같은 작업 폴더 Herdr Claude 독립 검토.
> 기준 HEAD: `d11461b52a0e2cb90521b3217d55f960d4c0676e` (`feat/status`).
> 실행 대상은 이 HEAD에 미커밋 검증 코드 및 G2-FIX-01 제품 변경을 더한 작업 트리다.
> 최종 G1: **PASS — 9개 프로젝트, 119개 테스트, 실패·오류·SKIP 0**.

## 제품 수정 후 최신 실행

G2-FIX-01의 입력 오류 처리 구현 후 `python3 scripts/run-g1-verification.py --offline`을 다시 실행했다. [최신 manifest](../.verification/33f3464bbf52/manifest.json)는 2026-09-28 16:39:10~16:40:53 KST의 **119개 PASS**를 기록한다. FoodMaterials는 회귀 테스트 6개를 추가해 44개이며, 다른 프로젝트는 아래 최초 결과와 동일하다. 실패·오류·SKIP 0, 소스 해시 전부 일치, G0 3종 PASS, 자원 정리 완료를 확인했다. 제품 변경과 후속 실제 HTTP 결과는 [G2 기록](g2-verification-results.md)에 있다.

아래는 검증기 최초 구현과 당시 113개 실행의 이력을 보존한 것이다. 과거 manifest의 해시 대조는 해당 실행 당시 파일 기준이다.

## 구현 범위

[`run-g1-verification.py`](../scripts/run-g1-verification.py)는 Java 21과 로컬 Docker를 확인하고 G0 정적 검사 3종 뒤 9개 Gradle 프로젝트의 테스트를 순서대로 실행한다. 별도 `runId`로 임시 디렉터리, 테스트 JVM, 컨테이너와 결과를 연결한다. 외부 Spring/DB/JWT/JVM 환경값을 상속하지 않고, 사용자 Gradle 설정 파일이 있으면 실행을 차단한다. 의존성 캐시는 기존 Gradle 캐시를 사용한다.

MariaDB·Redis·Kafka 테스트 컨테이너의 데이터는 tmpfs에 저장한다. 컨테이너 재사용을 끄고 Docker 생성 이벤트와 신규 컨테이너 목록을 함께 검사한다. 모듈별 필수 컨테이너가 관측되지 않거나 소유권·저장소를 확인할 수 없으면 PASS로 처리하지 않는다. 동일 Docker daemon에서 다른 컨테이너 작업을 동시에 실행하면 보수적으로 BLOCKED가 될 수 있다.

종료 시 실행 ID가 일치하는 JVM의 PID와 시작 시각을 확인하고 종료한 뒤 임시 컨테이너를 정리한다. 실행 전부터 존재한 컨테이너는 삭제 대상에서 제외한다. 일반 컨테이너는 실행 label과 Testcontainers label을 모두 확인하고, Ryuk은 검증된 컨테이너의 Testcontainers session과 일치하는 경우에만 정리한다. 볼륨 삭제·prune·Compose down은 수행하지 않는다.

FoodMaterials의 migration 테스트는 Git `788e59d`의 독립 V1 SQL 사본과 고정 SHA-256을 사용한다. Flyway로 만든 기존 V1 이력과 합성 카탈로그·재고·원장 데이터를 현재 migration 적용 후 비교한다. **과거 V1만 적용된 DB에서의 업그레이드 경로**를 검증하며, 과거 카탈로그 V2까지 이미 적용된 DB나 실제 운영 DB의 전환 증거는 아니다.

최초 G1 구현 단계의 변경은 검증 실행기·테스트 코드·테스트 fixture·결과 제외용 `.gitignore`와 문서다. 제품 `src/main`, 실제 DB migration, Compose, Gateway 경로, 서비스 목록과 Jenkins 설정은 변경 대상이 아니다.

## 실행 방법과 증거

저장소 루트에서 Docker Desktop과 Java 21을 준비한 뒤 실행한다.

```sh
python3 -m unittest scripts/test_g1_verification.py
python3 scripts/run-g1-verification.py --offline
```

`--offline`은 Gradle 의존성만 캐시로 제한한다. Docker 이미지가 없으면 Testcontainers가 내려받을 수 있다. Gradle 의존성 캐시가 없으면 해당 옵션을 제외한다. 기본 모듈 제한 시간은 900초다. 실행 중 검증 소스를 변경하면 최종 상태가 BLOCKED다.

`.verification/<runId>/manifest.json`에 전체·모듈별 상태, 테스트 수, 실행 명령, 소스 해시, 관측 컨테이너와 정리 결과를 기록한다. 모듈별 로그와 JUnit XML도 함께 보관한다. 기존 XML, 누락한 테스트 클래스, 필수 SKIP, 실패·오류, 부족한 컨테이너 증거는 PASS가 될 수 없다. 비밀값은 수집 시 가리고 결과는 Git에서 제외한다.

## 최초 구현 당시 실행 결과

최초 구현의 최종 전체 실행은 `python3 scripts/run-g1-verification.py --offline`이며, [manifest](../.verification/d30285c54cdd/manifest.json)가 원본 증거다. 2026-09-28 11:52:25~11:54:09 KST, Java 21.0.11 / Docker 29.8.0 / desktop-linux에서 실행했다. 기록된 소스 해시 전부를 당시 파일과 다시 대조해 차이가 없음을 확인했다.

| 프로젝트 | 실행 테스트 | 결과 |
|---|---:|---|
| eurekaServer | 1 | PASS |
| gatewayServer | 15 | PASS |
| AccountService | 35 | PASS |
| FoodMaterialsService | 38 | PASS |
| MenusService | 5 | PASS |
| NoticesService | 4 | PASS |
| BillsService | 4 | PASS |
| PurchaseService | 4 | PASS |
| DisposalsService | 7 | PASS |
| 합계 | 113 | 실패·오류·SKIP 0 |

G0 아키텍처 정적 검사의 기본·CI·performance 3종도 PASS다. 이는 원격 Jenkins 실행 결과가 아니다. 검증 컨테이너 11개를 관측했으며 필수 이미지 수와 tmpfs·소유권 조건을 충족했다. 종료 시 `cleanup.passed=true`, `helperCleanup.passed=true`, `processLeak=[]`, `lateContainers=[]`, `containerIssues=[]`, `finalizationErrors=[]`였다. 일반 테스트 컨테이너는 Testcontainers 종료 처리 과정에서 회수됐고, 실행 소유권을 확인한 Ryuk 1개는 실행기가 직접 제거했다.

### 최종 코드의 타임아웃·정리 실험

`python3 scripts/run-g1-verification.py --offline --module-timeout 12`의 [manifest](../.verification/9ecc642d9de0/manifest.json)도 당시 소스 해시와 전부 일치한다.

- Eureka·Gateway는 통과하고, Account는 MariaDB·Redis·Kafka 3개가 관측된 뒤 `timedOut=true`로 중단됐다.
- 이전 XML을 stale로 판정하고 Account는 BLOCKED, 뒤의 6개 프로젝트는 NOT_RUN으로 남겼다. 이 실행의 BLOCKED는 의도한 중단 결과이며 전체 G1 정상 실행의 PASS와 분리한다.
- 일반 테스트 컨테이너는 자동 회수됐고 실행기가 소유권을 확인한 Ryuk 1개를 제거했다. `cleanup`·`helperCleanup` 모두 PASS, `processLeak`·`lateContainers`·`containerIssues`·`finalizationErrors`는 빈 배열이다.
- 두 최종 runId의 JVM을 `ps`로 다시 확인한 결과 잔존 0, `docker ps -a --filter label=erpmsa.verification.run`도 결과가 비어 있었다.

따라서 실제 timeout 후 잔존 0과 helper 삭제 경로를 확인했다. 일반 DB 컨테이너를 실행기가 직접 `rm`하는 경로나 자동 삭제와 `rm`의 경합이 이 실험에서 강제로 재현됐다고 주장하지 않는다.

앞선 진단 실행 결과도 보존한다.

| runId | 결과 | 원인과 대응 |
|---|---|---|
| `3435744c36e3` | FAIL | Eureka Server에 client 비활성화 설정을 주입해 context 실패. Eureka에는 해당 설정을 주입하지 않도록 실행기 보정 |
| `c7db039dce95` | BLOCKED | Eureka 1개·Gateway 15개 통과 후 Kafka 이미지의 기본 영구 mount 발견. 선언된 데이터 경로를 모두 tmpfs로 보정 |
| `326bb3b77f30` | PASS | 중간 버전의 전체 G1 113개 통과. 이후 정리 처리가 바뀌어 최종 코드의 증거와 구분 |
| `e2a99fd9b225` | BLOCKED | 같은 Docker에서 별도 `erpmsa-ci-25` 컨테이너 생성 감지. 해당 자원은 삭제하지 않았고 이번 실행 자원만 정리 |
| `524c72ee41ed` | BLOCKED (의도한 중단) | 12초 제한으로 Account timedOut=true, MariaDB·Redis·Kafka 3개 관측. JVM·컨테이너·Ryuk 누수 없이 정리. 이후 정리 경합의 예외 기록 보완 전 실행임 |

재실행 통과가 앞선 실패·차단을 지우지는 않는다. 각 run의 상태와 로그를 별도로 유지한다.

## 독립 검토 반영

Claude가 지적한 컨테이너 관측 누락과 Gradle daemon·test worker 잔존 가능성에 대해 생성 이벤트·최소 관측 수·실행별 JVM marker·종료 후 재확인을 추가했다. 소스 해시를 테스트 파일에 한정하지 않고 문서를 제외한 추적·미추적 검증 입력 전체에 적용하며, 종료 시 다시 대조한다. 사용자 Gradle 설정을 통한 환경 재주입은 존재 여부 검사로 차단한다. 과거 migration 검증은 위에서 V1 경로로 범위를 한정했다.

Claude는 재검토에서 핵심 #1·#2의 거짓 PASS·외부 자원 삭제를 일으킬 차단 결함을 더 찾지 못했다고 답했다. 원본 응답을 수신하고 추가 의견에 따라 종료 단계별 오류와 2차 정리 결과를 보존하며, Ryuk의 자동 삭제와 정리가 겹칠 때 실제 잔존 여부를 다시 확인하도록 보완했다. 마지막 응답은 **최종 코드의 정리 예외 처리에 차단 결함 없음, 최종 코드로 전체·타임아웃 증거 재실행 필요**였다. 따라서 이전 PASS를 재사용하지 않고 위 최종 전체 실행을 수행했다. Claude의 검토는 읽기 전용 코드·기록 검토이며, 실행 결과의 최종 대조는 Codex가 수행했다.

안전성 단위 테스트는 17개다. 환경 상속, 소유권 거부, tmpfs, stale/누락/SKIP XML, 최소 컨테이너 수, 실행 ID와 PID 재사용, 이벤트 소실, Ryuk session·이름·label 불일치 및 삭제 경합을 검사한다.

제한사항: 컨테이너의 모듈 귀속은 이벤트를 처리한 시점의 모듈을 사용한다. 이벤트 처리가 오래 지연되면 모듈별 증거 귀속이 부정확할 수 있다. 실제 시험에서는 각 모듈의 필수 컨테이너 관측과 최종 자원 정리를 대조한다. 이번 V1 시험과 제한된 타임아웃 재현은 모든 과거 DB 상태나 모든 종료 경쟁 상황을 보장하지 않는다. 동일 daemon의 다른 session Ryuk도 새로 생겨 남아 있으면 보수적으로 BLOCKED 처리한다.

추가 제한: 일부 Docker 조회 오류에서는 helper가 이미 사라진 경우와 다른 조회 실패를 충분히 구분하지 못할 수 있고, 정리 블록 전체의 예외는 상세 정리 내역 일부를 대체할 수 있다. 최종 실행에는 이러한 오류가 없었다. 자동 삭제와 `rm`의 동시 경합은 단위 테스트로 확인했으며 실제 경합을 강제로 재현한 증거는 아니다.

## 남은 범위와 Annotate 검토 지점

G2 실제 3서비스 HTTP, G3 Gateway 전체 경로, G4 장애·복구, 원격 Jenkins와 배포/운영은 이번 실행 대상이 아니다. G1 통과만으로 정상 흐름 전체 완료를 선언하지 않는다.

Annotate에서는 다음을 검토한다.

- G1의 격리·관측·정리 정책과 증거가 다음 단계 진입에 충분한지.
- V1 migration 검증 범위와 추가 V2 이력 시나리오의 필요성.
- [정상 흐름 설계](normal-flow-verification-design.md)의 G2 대상 사례와 완료 조건.
