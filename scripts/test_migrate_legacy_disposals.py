"""Isolated MariaDB verification of the legacy disposal import CLI."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/migrate_legacy_disposals.py"
SOURCE_REASON = "유통기한\n'경과' \\"
SOURCE_ROWS = [
    dict(legacyDisposalId="D-01", legacyAccountId="shop-a", legacyFoodMaterialId="F-1",
         legacyReasonId="R-1", reason=SOURCE_REASON, quantity=3, legacyPrice=4200,
         disposedAt="2026-07-03 10:12:30.123456"),
    dict(legacyDisposalId="D-02", legacyAccountId="shop-b", legacyFoodMaterialId="F-2",
         legacyReasonId="R-2", reason="파손", quantity=2, legacyPrice=0,
         disposedAt="2026-07-04 00:00:00.000000"),
]
MAPPING = [
    dict(legacyAccountId="shop-a", legacyFoodMaterialId="F-1", accountId=101, foodMaterialId=201),
    dict(legacyAccountId="shop-b", legacyFoodMaterialId="F-2", accountId=102, foodMaterialId=202),
]


@unittest.skipUnless(os.environ.get("ERPMSA_TEST_LEGACY_MIGRATION") == "1", "opt-in isolated Docker test")
class LegacyDisposalMigrationTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="erpmsa-legacy-disposal-")
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name).resolve()
        self.container = "erpmsa-legacy-disposal-" + secrets.token_hex(6)
        self.password = secrets.token_hex(20)
        self.command(
            "docker", "run", "-d", "--rm", "--pull", "never", "--network", "none", "--name", self.container,
            "--label", "erpmsa.test=legacy-disposal", "--tmpfs", "/var/lib/mysql:rw",
            "--mount", f"type=bind,source={self.folder},target=/fixture,readonly",
            "--env", "MARIADB_ALLOW_EMPTY_ROOT_PASSWORD=1",
            "--env", "MARIADB_ROOT_HOST=localhost", "mariadb:10.11",
        )
        self.addCleanup(subprocess.run, ["docker", "rm", "-f", self.container], capture_output=True)
        inspected = json.loads(self.command("docker", "inspect", self.container).stdout)[0]
        self.assertEqual("none", inspected["HostConfig"]["NetworkMode"])
        self.assertIn("/var/lib/mysql", inspected["HostConfig"]["Tmpfs"])
        self.assertFalse(any(mount["Type"] == "volume" for mount in inspected["Mounts"]))
        for _ in range(60):
            probe = self.command("docker", "exec", self.container, "healthcheck.sh",
                                 "--connect", "--innodb_initialized", check=False)
            if probe.returncode == 0:
                break
            time.sleep(.5)
        else:
            self.fail("isolated MariaDB did not become ready")
        # The container has no network. Protect root before running fixture queries.
        self.command("docker", "exec", "-i", self.container, "mariadb", "-uroot", "--skip-password",
                     input=f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{self.password}';\n")
        wrapper = f"""#!/bin/sh
config=${{1##*/}}
shift
exec docker exec -i --env MYSQL_PWD {shlex.quote(self.container)} mariadb "--defaults-file=/fixture/$config" "$@"
"""
        self.client = self.write("test-mariadb", wrapper, mode=0o700)
        self.source = self.write("source.cnf", "[client]\nuser=exporter\n")
        self.target = self.write("target.cnf", "[client]\nuser=importer\n")
        self.sql(f"""
CREATE DATABASE legacy;
CREATE DATABASE itemdb;
CREATE DATABASE inventorydb;
CREATE DATABASE disposalsdb;
CREATE USER 'exporter'@'localhost' IDENTIFIED BY '{self.password}';
CREATE USER 'importer'@'localhost' IDENTIFIED BY '{self.password}';
CREATE TABLE legacy.FOODM (foodMaterial_Id VARCHAR(50) PRIMARY KEY, bId VARCHAR(50), totalWeight INT);
CREATE TABLE legacy.REASON (reason_Id VARCHAR(50) PRIMARY KEY, reason VARCHAR(255));
CREATE TABLE legacy.DISPOSALS (
    disposal_Id VARCHAR(50) PRIMARY KEY, foodMaterial_Id VARCHAR(50), reason_Id VARCHAR(50),
    disposalCountAll INT, disposalPrice INT, disposalDate DATETIME(6)
);
INSERT INTO legacy.FOODM VALUES ('F-1', 'shop-a', 17), ('F-2', 'shop-b', 23);
INSERT INTO legacy.REASON VALUES ('R-1', CONVERT(X'{SOURCE_REASON.encode().hex()}' USING utf8mb4)), ('R-2', '파손');
INSERT INTO legacy.DISPOSALS VALUES
    ('D-01', 'F-1', 'R-1', 3, 4200, '2026-07-03 10:12:30.123456'),
    ('D-02', 'F-2', 'R-2', 2, 0, '2026-07-04 00:00:00');
GRANT SELECT ON legacy.DISPOSALS TO 'exporter'@'localhost';
GRANT SELECT ON legacy.FOODM TO 'exporter'@'localhost';
GRANT SELECT ON legacy.REASON TO 'exporter'@'localhost';
""")
        self.schema("itemdb", "FoodMaterialsService/src/main/resources/db/migration/V1__create_item_schema.sql")
        self.schema("inventorydb", "FoodMaterialsService/src/main/resources/db/inventory-migration/V1__create_inventory_schema.sql")
        self.schema("inventorydb", "FoodMaterialsService/src/main/resources/db/inventory-migration/V2__allow_disposal_movements.sql")
        self.schema("disposalsdb", "DisposalsService/src/main/resources/db/migration/V1__create_disposal_schema.sql")
        self.schema("disposalsdb", "scripts/sql/create-legacy-disposal-history.sql")
        self.sql("""
INSERT INTO itemdb.item (id, account_id, sku, name, unit_price, status, created_at, updated_at) VALUES
    (201, 101, 'sku-a', 'item a', 100, 'ACTIVE', NOW(), NOW()),
    (202, 102, 'sku-b', 'item b', 200, 'INACTIVE', NOW(), NOW()),
    (203, 101, 'sku-c', 'item c', 300, 'ACTIVE', NOW(), NOW());
INSERT INTO inventorydb.inventory (id, account_id, item_id, on_hand_quantity, version, created_at, updated_at) VALUES
    (301, 101, 201, 17, 4, NOW(), NOW()), (302, 102, 202, 23, 1, NOW(), NOW());
INSERT INTO inventorydb.stock_movement (inventory_id, account_id, item_id, request_id, movement_type,
    quantity_delta, quantity_before, quantity_after, reason, created_at) VALUES
    (301, 101, 201, 'opening-a', 'INITIAL', 17, 0, 17, 'initial', NOW()),
    (302, 102, 202, 'opening-b', 'INITIAL', 23, 0, 23, 'initial', NOW());
INSERT INTO disposalsdb.disposal (id, account_id, request_id, food_material_id, quantity, reason, status, created_at, updated_at)
    VALUES ('70130aca-211b-47f5-a3e3-9f674c977d51', 101, 'current', 201, 2, 'existing', 'PENDING', NOW(), NOW());
GRANT SELECT, INSERT ON disposalsdb.legacy_disposal_history TO 'importer'@'localhost';
GRANT CREATE TEMPORARY TABLES ON disposalsdb.* TO 'importer'@'localhost';
GRANT SELECT (id, account_id) ON itemdb.item TO 'importer'@'localhost';
""")
        self.mapping = self.write("mapping.json", json.dumps(MAPPING))

    def command(self, *args, check=True, **kwargs):
        result = subprocess.run(args, capture_output=True, encoding="utf-8", **kwargs)
        if check:
            self.assertEqual(0, result.returncode, result.stderr)
        return result

    def sql(self, sql):
        return self.command(
            "docker", "exec", "-i", "--env", "MYSQL_PWD", self.container,
            "mariadb", "-uroot", "-BN", "--raw", "--default-character-set=utf8mb4",
            input=sql, env={**os.environ, "MYSQL_PWD": self.password},
        ).stdout

    def schema(self, database, path):
        self.sql(f"USE {database};\n" + (ROOT / path).read_text())

    def write(self, name, content, mode=0o600):
        path = self.folder / name
        path.write_text(content, encoding="utf-8")
        path.chmod(mode)
        return path

    def snapshot(self, rows):
        return self.write("disposals.jsonl", "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))

    def cli(self, *args, check=True):
        return self.command(sys.executable, str(CLI), "--client", str(self.client),
                            *map(str, args), check=check, env={**os.environ, "MYSQL_PWD": self.password})

    def apply(self, snapshot, mapping=None, check=True):
        return self.cli("import", snapshot, mapping or self.mapping, "--apply", "--config", self.target, check=check)

    def protected_state(self):
        return self.sql("""
START TRANSACTION READ ONLY;
SELECT * FROM legacy.DISPOSALS ORDER BY disposal_Id;
SELECT * FROM legacy.FOODM ORDER BY foodMaterial_Id;
SELECT * FROM legacy.REASON ORDER BY reason_Id;
SELECT * FROM itemdb.item ORDER BY id;
SELECT * FROM inventorydb.inventory ORDER BY id;
SELECT * FROM inventorydb.stock_movement ORDER BY id;
SELECT * FROM disposalsdb.disposal ORDER BY id;
ROLLBACK;
""")

    def archive(self):
        return self.sql("SELECT * FROM disposalsdb.legacy_disposal_history ORDER BY legacy_disposal_id;")

    def test_export_apply_rerun_conflicts_and_concurrent_replay(self):
        before = self.protected_state()
        exported = self.cli("export", "--database", "legacy", "--config", self.source).stdout
        self.assertEqual(SOURCE_ROWS, [json.loads(row) for row in exported.splitlines()])
        snapshot = self.write("exported.jsonl", exported)
        self.assertEqual({"mode": "validate", "rows": 2}, json.loads(self.cli("import", snapshot, self.mapping).stdout))
        self.assertEqual("", self.archive())
        self.assertEqual({"mode": "apply", "inserted": 2, "unchanged": 0}, json.loads(self.apply(snapshot).stdout))
        archive = self.archive()
        fields = self.sql("""
SELECT JSON_ARRAY(legacy_disposal_id, legacy_account_id, legacy_food_material_id, legacy_reason_id,
    reason, quantity, legacy_price, legacy_disposed_at, account_id, food_material_id)
FROM disposalsdb.legacy_disposal_history ORDER BY legacy_disposal_id;
""")
        self.assertEqual(
            [[*row.values(), entry["accountId"], entry["foodMaterialId"]] for row, entry in zip(SOURCE_ROWS, MAPPING)],
            [json.loads(row) for row in fields.splitlines()],
        )
        self.assertEqual(before, self.protected_state())
        self.assertEqual({"mode": "apply", "inserted": 0, "unchanged": 2}, json.loads(self.apply(snapshot).stdout))
        self.assertEqual(archive, self.archive())
        self.assertEqual(before, self.protected_state())

        changed = dict(SOURCE_ROWS[0], legacyPrice=4201)
        new = dict(SOURCE_ROWS[0], legacyDisposalId="D-03")
        conflict = self.apply(self.snapshot([new, changed]), check=False)
        self.assertEqual(1, conflict.returncode)
        self.assertIn("저장된 이력과 입력이 다릅니다", conflict.stderr)
        self.assertEqual(archive, self.archive())

        wrong_owner = self.write("wrong-owner.json", json.dumps([dict(MAPPING[0], accountId=102)]))
        failure = self.apply(self.snapshot([new]), wrong_owner, check=False)
        self.assertEqual(1, failure.returncode)
        self.assertIn("계정 소유권", failure.stderr)
        self.assertEqual(archive, self.archive())

        changed_mapping = self.write("changed-mapping.json", json.dumps([dict(MAPPING[0], foodMaterialId=203)]))
        failure = self.apply(self.snapshot([new]), changed_mapping, check=False)
        self.assertEqual(1, failure.returncode)
        self.assertIn("이미 이관된 계정 또는 식자재 매핑", failure.stderr)
        self.assertEqual(archive, self.archive())

        concurrent_snapshot = self.snapshot([new])
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: json.loads(self.apply(concurrent_snapshot).stdout), range(2)))
        self.assertCountEqual([(1, 0), (0, 1)], [(r["inserted"], r["unchanged"]) for r in results])
        self.assertEqual("3\n", self.sql("SELECT COUNT(*) FROM disposalsdb.legacy_disposal_history;"))
        self.assertEqual(before, self.protected_state())


if __name__ == "__main__":
    unittest.main()
