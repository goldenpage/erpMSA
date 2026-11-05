-- Only for the disposable verification database; never loaded into existing DBs.
CREATE TABLE USERINFO (
  bId VARCHAR(10) PRIMARY KEY, name VARCHAR(100), phone VARCHAR(100), email VARCHAR(255),
  storeName VARCHAR(255), storeType VARCHAR(100), storeCategory VARCHAR(100), pw VARCHAR(255),
  signDate DATETIME(6), agreementDate DATETIME(6), marketingDate DATETIME(6)
);
CREATE TABLE account (
  id INT PRIMARY KEY AUTO_INCREMENT, username VARCHAR(255) UNIQUE NOT NULL,
  password VARCHAR(255) NOT NULL, role VARCHAR(255) NOT NULL, email VARCHAR(255),
  name VARCHAR(255), created DATETIME(6)
);
CREATE TABLE admin_user (
  admin_id INT PRIMARY KEY AUTO_INCREMENT, admin_name VARCHAR(255) UNIQUE NOT NULL,
  pw VARCHAR(255) NOT NULL, role VARCHAR(255) NOT NULL, created_at DATE NOT NULL
);
CREATE TABLE registration_requested_user (
  review_id INT PRIMARY KEY AUTO_INCREMENT, b_id VARCHAR(10) NOT NULL,
  pw_hash VARCHAR(255) NOT NULL, name VARCHAR(255), email VARCHAR(255), phone VARCHAR(255),
  store_name VARCHAR(255), store_type VARCHAR(255), store_category VARCHAR(255),
  marketing_agree BOOLEAN NOT NULL, document_path VARCHAR(255) NOT NULL,
  ocr_confidence VARCHAR(255), reason VARCHAR(1000), reviewed_by VARCHAR(255),
  requested_at DATETIME(6) NOT NULL, review_date DATETIME(6), review_status VARCHAR(30) NOT NULL
);
