CREATE TABLE account (
    id BIGINT NOT NULL AUTO_INCREMENT,
    b_id VARCHAR(10) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    document_path VARCHAR(255) NULL,
    email VARCHAR(255) NOT NULL,
    marketing_agreed BIT(1) NOT NULL,
    name VARCHAR(50) NOT NULL,
    ocr_confidence VARCHAR(255) NULL,
    phone VARCHAR(20) NULL,
    pw_hash VARCHAR(255) NOT NULL,
    reason VARCHAR(255) NULL,
    review_date DATETIME(6) NULL,
    review_status ENUM(
        'ACTIVE',
        'PENDING',
        'REJECTED',
        'SUSPENDED',
        'WITHDRAWN'
    ) NOT NULL,
    role ENUM('ROLE_MANAGER', 'ROLE_USER') NOT NULL,
    store_category VARCHAR(50) NULL,
    store_name VARCHAR(100) NOT NULL,
    store_type VARCHAR(50) NULL,
    updated_at DATETIME(6) NOT NULL,
    username VARCHAR(255) NULL,
    CONSTRAINT accountEmail UNIQUE (email),
    CONSTRAINT accountBusinessId UNIQUE (b_id),
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE refresh_token (
    token_id BIGINT NOT NULL AUTO_INCREMENT,
    expiry_date DATETIME(6) NULL,
    token VARCHAR(255) NULL,
    username VARCHAR(255) NULL,
    PRIMARY KEY (token_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
