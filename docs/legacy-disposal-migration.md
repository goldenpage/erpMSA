# 레거시 폐기 이력 이관

KostaErp의 `DISPOSALS`는 `FOODM` 재고 차감과 같은 트랜잭션에서 저장된다. 이관 대상은 이미 처리된 폐기 이력이다. MSA에서는 `disposalsdb.legacy_disposal_history`에 저장하고 SQL로 조회한다. `/disposals`는 MSA에서 생성한 처리 요청의 목록·상세·재시도를 담당한다.

원본 폐기 ID, 계정·식자재·사유 ID, 사유 본문, 수량, 금액, 날짜를 보존하고 MSA 계정·식자재 ID를 함께 저장한다. 날짜와 시각은 레거시 DB에서 받은 ISO 날짜 또는 날짜·시각 문자열을 보존한다. 기존 현재고를 기준으로 이력을 적재하며 이관 도구의 쓰기 범위는 이력 테이블의 `INSERT`다. 재고 이관이 필요한 환경에서는 현재고 적재와 대조를 별도로 완료한다.

## 실행

Python 3와 MariaDB 클라이언트가 필요하다. 아래 예시는 서로 분리된 레거시 스냅샷 DB와 MSA 대상 DB를 지정하는 경우다. 접속 설정은 접근이 제한된 클라이언트 옵션 파일의 `[client]`에 저장한다.

1. 원본 `DISPOSALS`, `FOODM`, `REASON`에 SELECT 권한을 가진 계정으로 스냅샷을 내보낸다. 원본 참조가 누락되거나 폐기 ID가 중복되면 내보내기가 실패한다.

   ```sh
   umask 077
   python3 scripts/migrate_legacy_disposals.py export \
     --database legacy_snapshot --config /secure/legacy-reader.cnf > legacy-disposals.jsonl
   ```

2. 실제 계정·카탈로그를 대조한 매핑을 JSON 배열로 작성한다. 원본 계정·식자재 조합별로 하나씩 기입한다. 아래 값은 예시다.

   ```json
   [
     {
       "legacyAccountId": "shop-a",
       "legacyFoodMaterialId": "F-1",
       "accountId": 101,
       "foodMaterialId": 201
     }
   ]
   ```

   `--apply`를 생략하면 로컬 파일의 형식과 매핑 누락을 검증한다.

   ```sh
   python3 scripts/migrate_legacy_disposals.py import legacy-disposals.jsonl mapping.json
   ```

3. MSA 대상 `disposalsdb`에 이력 테이블을 준비한다. 기존 Flyway와 분리된 1회 설정이다. 가져오기 계정에는 이력 테이블의 SELECT·INSERT, `disposalsdb`의 CREATE TEMPORARY TABLES, `itemdb.item`의 `id`·`account_id` SELECT 권한을 부여한다.

   ```sh
   mariadb --defaults-file=/secure/msa-schema-admin.cnf < scripts/sql/create-legacy-disposal-history.sql
   python3 scripts/migrate_legacy_disposals.py import legacy-disposals.jsonl mapping.json \
     --apply --config /secure/msa-history-importer.cnf
   ```

4. 대상 계정의 이력을 확인한다.

   ```sql
   SELECT legacy_disposal_id, food_material_id, quantity, legacy_price, legacy_disposed_at, reason
   FROM disposalsdb.legacy_disposal_history
   WHERE account_id = 101
   ORDER BY legacy_disposed_at DESC, legacy_disposal_id DESC;
   ```

신규 행의 매핑은 MSA 식자재 카탈로그의 계정 소유권과 대조한다. 동일한 원본 ID와 값은 `unchanged`로 집계한다. 같은 ID의 값이 달라졌거나 기존 매핑과 충돌하면 전체 배치가 실패한다. 가져오기 프로세스는 같은 MariaDB의 이름 잠금으로 직렬화하며, 배치는 한 트랜잭션으로 삽입한다. [MariaDB 이름 잠금](https://mariadb.com/docs/server/reference/sql-functions/secondary-functions/miscellaneous-functions/get_lock)

## 격리 검증

```sh
ERPMSA_TEST_LEGACY_MIGRATION=1 python3 -m unittest discover -s scripts -p 'test_migrate_legacy_disposals.py' -v
```

테스트는 네트워크가 없는 일회용 MariaDB 10.11의 tmpfs에 레거시 예제와 MSA 스키마를 만든다. 첫 실행의 2건 삽입, 동일 배치 재실행의 0건 삽입, 원본 ID 충돌과 소유권·매핑 불일치의 배치 거절, 동시 실행의 단일 삽입을 확인한다. 원본 필드, 레거시 재고, MSA 카탈로그·현재고·원장·기존 폐기 요청을 행 단위로 대조한다.
