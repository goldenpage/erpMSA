CREATE TABLE inventory (
    id BIGINT NOT NULL AUTO_INCREMENT,
    account_id BIGINT NOT NULL,
    item_id BIGINT NOT NULL,
    on_hand_quantity BIGINT NOT NULL,
    version BIGINT NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    CONSTRAINT uk_inventory_account_item UNIQUE (account_id, item_id),
    CONSTRAINT chk_inventory_quantity CHECK (on_hand_quantity >= 0),
    PRIMARY KEY (id),
    INDEX idx_inventory_account_updated (account_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE stock_movement (
    id BIGINT NOT NULL AUTO_INCREMENT,
    inventory_id BIGINT NOT NULL,
    account_id BIGINT NOT NULL,
    item_id BIGINT NOT NULL,
    request_id VARCHAR(64) NOT NULL,
    movement_type VARCHAR(20) NOT NULL,
    quantity_delta BIGINT NOT NULL,
    quantity_before BIGINT NOT NULL,
    quantity_after BIGINT NOT NULL,
    reason VARCHAR(255) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    CONSTRAINT uk_movement_account_request UNIQUE (account_id, request_id),
    CONSTRAINT chk_movement_type CHECK (
        movement_type IN ('INITIAL', 'ADJUSTMENT')
    ),
    CONSTRAINT chk_movement_quantity_after CHECK (quantity_after >= 0),
    CONSTRAINT fk_movement_inventory FOREIGN KEY (inventory_id)
        REFERENCES inventory (id),
    PRIMARY KEY (id),
    INDEX idx_movement_inventory_created (inventory_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
