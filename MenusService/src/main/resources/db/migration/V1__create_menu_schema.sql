CREATE TABLE menu (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    account_id BIGINT NOT NULL,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(1000),
    price DECIMAL(15,2) NOT NULL,
    status VARCHAR(20) NOT NULL,
    version BIGINT NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    CONSTRAINT chk_menu_price CHECK (price >= 0),
    CONSTRAINT chk_menu_status CHECK (status IN ('ACTIVE','INACTIVE')),
    INDEX idx_menu_account_created (account_id,created_at,id),
    INDEX idx_menu_account_status_created (account_id,status,created_at,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
