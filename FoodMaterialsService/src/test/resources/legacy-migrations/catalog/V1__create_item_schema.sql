CREATE TABLE item (
    id BIGINT NOT NULL AUTO_INCREMENT,
    account_id BIGINT NOT NULL,
    sku VARCHAR(64) NOT NULL,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(1000) NULL,
    unit_price DECIMAL(15, 2) NOT NULL,
    status VARCHAR(20) NOT NULL,
    version BIGINT NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    CONSTRAINT uk_item_account_sku UNIQUE (account_id, sku),
    CONSTRAINT chk_item_unit_price CHECK (unit_price >= 0),
    CONSTRAINT chk_item_status CHECK (status IN ('ACTIVE', 'INACTIVE')),
    PRIMARY KEY (id),
    INDEX idx_item_account_status (account_id, status),
    INDEX idx_item_account_created (account_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
