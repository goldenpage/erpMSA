# Independent historical migration fixtures

Copied byte-for-byte from Git revision `788e59d2dfe0be7a42c896b0afc08baa303c834d`:

- `ItemService/src/main/resources/db/migration/V1__create_item_schema.sql` → `catalog/`.
- `InventoryService/src/main/resources/db/migration/V1__create_inventory_schema.sql` → `inventory/`.

`LegacyMigrationFixture` verifies pinned SHA-256 hashes before Flyway creates V1 history.
The application then applies current migrations; tests compare the original V1 history and data.
Do not regenerate these fixtures from current `src/main/resources` migrations or use baseline/repair.
