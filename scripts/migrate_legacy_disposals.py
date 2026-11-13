#!/usr/bin/env python3
"""Export legacy KostaErp disposals and import them into the MSA history archive."""

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import re
import subprocess
import sys


EXPORT_SQL = """
START TRANSACTION READ ONLY;
SELECT JSON_OBJECT(
    'legacyDisposalId', CAST(d.disposal_Id AS CHAR),
    'legacyAccountId', CAST(f.bId AS CHAR),
    'legacyFoodMaterialId', CAST(d.foodMaterial_Id AS CHAR),
    'legacyReasonId', CAST(d.reason_Id AS CHAR),
    'reason', r.reason,
    'quantity', d.disposalCountAll,
    'legacyPrice', d.disposalPrice,
    'disposedAt', CAST(d.disposalDate AS CHAR)
)
FROM DISPOSALS d
LEFT JOIN FOODM f ON f.foodMaterial_Id = d.foodMaterial_Id
LEFT JOIN REASON r ON r.reason_Id = d.reason_Id
ORDER BY d.disposal_Id;
ROLLBACK;
"""
FIELDS = {
    "legacyDisposalId": "legacy_disposal_id",
    "legacyAccountId": "legacy_account_id",
    "legacyFoodMaterialId": "legacy_food_material_id",
    "legacyReasonId": "legacy_reason_id",
    "reason": "reason",
    "quantity": "quantity",
    "legacyPrice": "legacy_price",
    "disposedAt": "legacy_disposed_at",
    "accountId": "account_id",
    "foodMaterialId": "food_material_id",
}
SOURCE_FIELDS = set(FIELDS) - {"accountId", "foodMaterialId"}
MAPPING_FIELDS = {"legacyAccountId", "legacyFoodMaterialId", "accountId", "foodMaterialId"}
TABLE = "legacy_disposal_history"
STAGING = "pending_legacy_disposal"
COLUMNS = ", ".join(FIELDS.values())
COMPARE = " OR ".join(
    f"BINARY saved.{name} <> BINARY incoming.{name}"
    for name in list(FIELDS.values())[1:]
)
APPLY_SQL = f"""
DELIMITER //
BEGIN NOT ATOMIC
    DECLARE lock_acquired INT DEFAULT 0;
    DECLARE added BIGINT DEFAULT 0;
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        IF lock_acquired = 1 THEN
            DO RELEASE_LOCK('disposalsdb.legacy_disposal_history');
        END IF;
        RESIGNAL;
    END;

    SET lock_acquired = GET_LOCK('disposalsdb.legacy_disposal_history', 10);
    IF NOT (lock_acquired <=> 1) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'LEGACY_HISTORY_BUSY';
    END IF;

    START TRANSACTION;
    IF EXISTS (
        SELECT 1 FROM {STAGING} incoming
        LEFT JOIN {TABLE} saved USING (legacy_disposal_id)
        LEFT JOIN itemdb.item item ON item.id = incoming.food_material_id
                                  AND item.account_id = incoming.account_id
        WHERE saved.legacy_disposal_id IS NULL AND item.id IS NULL
    ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'LEGACY_MAPPING_OWNER_MISMATCH';
    END IF;

    IF EXISTS (
        SELECT 1 FROM {STAGING} incoming JOIN {TABLE} saved USING (legacy_disposal_id)
        WHERE {COMPARE}
    ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'LEGACY_HISTORY_CONFLICT';
    END IF;

    IF EXISTS (
        SELECT 1 FROM (
            SELECT DISTINCT legacy_account_id, account_id, legacy_food_material_id, food_material_id
            FROM {STAGING}
        ) incoming
        JOIN {TABLE} saved ON saved.legacy_account_id = incoming.legacy_account_id
        WHERE saved.account_id <> incoming.account_id
           OR (saved.legacy_food_material_id = incoming.legacy_food_material_id
               AND saved.food_material_id <> incoming.food_material_id)
    ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'LEGACY_MAPPING_CONFLICT';
    END IF;

    INSERT INTO {TABLE} ({COLUMNS})
    SELECT {", ".join("incoming." + name for name in FIELDS.values())}
    FROM {STAGING} incoming
    LEFT JOIN {TABLE} saved USING (legacy_disposal_id)
    WHERE saved.legacy_disposal_id IS NULL;
    SET added = ROW_COUNT();
    COMMIT;
    DO RELEASE_LOCK('disposalsdb.legacy_disposal_history');
    SELECT added, (SELECT COUNT(*) FROM {STAGING}) - added;
END//
DELIMITER ;
"""
DB_ERRORS = {
    "LEGACY_HISTORY_BUSY": "다른 이관이 진행 중입니다.",
    "LEGACY_MAPPING_OWNER_MISMATCH": "MSA 카탈로그에서 매핑된 식자재의 계정 소유권을 확인할 수 없습니다.",
    "LEGACY_HISTORY_CONFLICT": "같은 원본 폐기 ID에 저장된 이력과 입력이 다릅니다.",
    "LEGACY_MAPPING_CONFLICT": "입력 매핑이 이미 이관된 계정 또는 식자재 매핑과 다릅니다.",
}


def run_sql(client, config, database, sql):
    result = subprocess.run(
        [client, f"--defaults-file={config.resolve(strict=True)}", "--batch", "--raw",
         "--skip-column-names", "--default-character-set=utf8mb4", "--local-infile=0",
         "--skip-reconnect", "--skip-force", "--connect-timeout=5", f"--database={database}"],
        input=sql, capture_output=True, encoding="utf-8",
    )
    if result.returncode:
        match = re.search(r"^ERROR (\d+)(?: \([0-9A-Z]+\))?(?: at line \d+)?: ([^\r\n]+)",
                          result.stderr, re.MULTILINE)
        if match and match[2] in DB_ERRORS:
            raise ValueError(DB_ERRORS[match[2]])
        code = f" (DB 오류 {match[1]})" if match else ""
        raise ValueError(f"DB 명령이 실패했습니다{code}. 연결, 권한 및 대상 스키마를 확인하세요.")
    return result.stdout


def identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 255 and value.strip() == value and "\x00" not in value


def integer(value, minimum):
    return type(value) is int and minimum <= value <= 2**63 - 1


def validate_date(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d\d-\d\d(?: \d\d:\d\d:\d\d(?:\.\d{1,6})?)?", value, re.ASCII
    ):
        return False
    try:
        if len(value) == 10:
            date.fromisoformat(value)
        else:
            datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def unique_fields(pairs):
    fields = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError("JSON 객체에 같은 필드가 여러 번 있습니다.")
        fields[key] = value
    return fields


def read_snapshot(lines):
    seen = set()
    for number, line in enumerate(lines, start=1):
        row = json.loads(line, object_pairs_hook=unique_fields)
        if (not isinstance(row, dict) or set(row) != SOURCE_FIELDS
                or not all(identifier(row[field]) for field in (
                    "legacyDisposalId", "legacyAccountId", "legacyFoodMaterialId", "legacyReasonId"
                ))
                or not isinstance(row["reason"], str) or not row["reason"].strip()
                or len(row["reason"].encode("utf-8")) > 65535
                or not integer(row["quantity"], 1) or not integer(row["legacyPrice"], 0)
                or not validate_date(row["disposedAt"])):
            raise ValueError(f"스냅샷 {number}행의 필드, 원본 참조 또는 값이 올바르지 않습니다.")
        if row["legacyDisposalId"] in seen:
            raise ValueError(f"스냅샷 {number}행의 원본 폐기 ID가 중복됩니다.")
        seen.add(row["legacyDisposalId"])
        yield row


def read_mapping(path):
    entries = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_fields)
    if not isinstance(entries, list):
        raise ValueError("매핑은 JSON 배열이어야 합니다.")
    owners = {}
    mapping = {}
    for number, entry in enumerate(entries, start=1):
        if (not isinstance(entry, dict) or set(entry) != MAPPING_FIELDS
                or not all(identifier(entry[field]) for field in ("legacyAccountId", "legacyFoodMaterialId"))
                or not all(integer(entry[field], 1) for field in ("accountId", "foodMaterialId"))):
            raise ValueError(f"매핑 {number}번째 항목의 필드 또는 값이 올바르지 않습니다.")
        owner, item = entry["legacyAccountId"], entry["legacyFoodMaterialId"]
        account_id, material_id = entry["accountId"], entry["foodMaterialId"]
        if (owner, item) in mapping or owners.setdefault(owner, account_id) != account_id:
            raise ValueError(f"매핑 {number}번째 항목의 원본 식자재가 중복되거나 원본 계정의 대상이 다릅니다.")
        mapping[owner, item] = account_id, material_id
    return mapping


def mapped_rows(snapshot, mapping):
    with snapshot.open(encoding="utf-8") as lines:
        for number, row in enumerate(read_snapshot(lines), start=1):
            pair = row["legacyAccountId"], row["legacyFoodMaterialId"]
            if pair not in mapping:
                raise ValueError(f"스냅샷 {number}행의 계정·식자재 매핑이 없습니다.")
            row["accountId"], row["foodMaterialId"] = mapping[pair]
            yield row


def import_sql(rows):
    statements = [
        "SET SESSION sql_mode = 'STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION';",
        f"CREATE TEMPORARY TABLE {STAGING} LIKE {TABLE};",
    ]
    for row in rows:
        # Text travels as UTF-8 hex, so SQL mode and data characters cannot alter the statement.
        values = ", ".join(
            str(value) if type(value) is int else f"CONVERT(X'{value.encode('utf-8').hex()}' USING utf8mb4)"
            for value in (row[key] for key in FIELDS)
        )
        statements.append(f"INSERT INTO {STAGING} ({COLUMNS}) VALUES ({values});")
    return "\n".join([*statements, APPLY_SQL])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", default="mariadb", help="MariaDB 호환 클라이언트 경로")
    modes = parser.add_subparsers(dest="mode", required=True)
    export = modes.add_parser("export", help="레거시 DB를 SELECT로 조회해 JSONL 출력")
    export.add_argument("--config", type=Path, required=True, help="레거시 조회 전용 클라이언트 옵션 파일")
    export.add_argument("--database", required=True, help="레거시 DB 스키마")
    load = modes.add_parser("import", help="스냅샷과 매핑을 검사하거나 명시적으로 이관")
    load.add_argument("snapshot", type=Path)
    load.add_argument("mapping", type=Path)
    load.add_argument("--apply", action="store_true", help="disposalsdb 이력 테이블에 반영")
    load.add_argument("--config", type=Path, help="대상 전용 클라이언트 옵션 파일")
    args = parser.parse_args()
    try:
        if args.mode == "export":
            result = run_sql(args.client, args.config, args.database, EXPORT_SQL)
            rows = list(read_snapshot(result.removesuffix("\n").split("\n") if result else []))
            for row in rows:
                print(json.dumps(row, ensure_ascii=False))
            return 0

        if args.apply != (args.config is not None):
            parser.error("--apply와 --config는 함께 지정하세요.")
        rows = list(mapped_rows(args.snapshot, read_mapping(args.mapping)))
        if not args.apply:
            print(json.dumps({"mode": "validate", "rows": len(rows)}))
            return 0
        added, skipped = map(int, run_sql(args.client, args.config, "disposalsdb", import_sql(rows)).split())
        print(json.dumps({"mode": "apply", "inserted": added, "unchanged": skipped}))
        return 0
    except (OSError, ValueError) as error:
        print(f"폐기 이관 실패 | {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
