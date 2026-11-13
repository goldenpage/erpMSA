-- Provision separately from Flyway. The importer only inserts into this table.
CREATE TABLE IF NOT EXISTS disposalsdb.legacy_disposal_history (
    legacy_disposal_id VARCHAR(255) NOT NULL PRIMARY KEY,
    legacy_account_id VARCHAR(255) NOT NULL,
    legacy_food_material_id VARCHAR(255) NOT NULL,
    legacy_reason_id VARCHAR(255) NOT NULL,
    reason TEXT NOT NULL,
    quantity BIGINT NOT NULL CHECK (quantity > 0),
    legacy_price BIGINT NOT NULL CHECK (legacy_price >= 0),
    legacy_disposed_at VARCHAR(26) NOT NULL,
    account_id BIGINT NOT NULL CHECK (account_id > 0),
    food_material_id BIGINT NOT NULL CHECK (food_material_id > 0),
    INDEX idx_legacy_disposal_mapping (legacy_account_id, legacy_food_material_id),
    INDEX idx_legacy_disposal_history (account_id, legacy_disposed_at, legacy_disposal_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
