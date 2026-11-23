CREATE TABLE accounts (
  id INT PRIMARY KEY AUTO_INCREMENT,
  email VARCHAR(120) UNIQUE NOT NULL,
  password_hash VARCHAR(160) NOT NULL,
  role ENUM('admin','analyst','viewer') NOT NULL
);
CREATE TABLE sessions (
  id INT PRIMARY KEY AUTO_INCREMENT,
  code VARCHAR(24) UNIQUE NOT NULL,
  title VARCHAR(80) NOT NULL,
  recorded_on DATE NOT NULL,
  start_time VARCHAR(5) NOT NULL,
  band ENUM('early','day','late') NOT NULL,
  room VARCHAR(48) NOT NULL,
  note VARCHAR(350) NOT NULL
);
CREATE TABLE readings (
  id INT PRIMARY KEY AUTO_INCREMENT,
  session_id INT NOT NULL,
  reference VARCHAR(64) NOT NULL,
  hvac ENUM('quiet','normal','boost') NOT NULL,
  position ENUM('booth','street','door') NOT NULL,
  traffic INT NOT NULL CHECK (traffic BETWEEN 0 AND 1000),
  noise DECIMAL(5,2) NOT NULL CHECK (noise BETWEEN 0 AND 140),
  note VARCHAR(350) NOT NULL,
  UNIQUE (session_id, reference),
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE TABLE methods (
  id INT PRIMARY KEY AUTO_INCREMENT,
  version VARCHAR(32) UNIQUE NOT NULL,
  title VARCHAR(80) NOT NULL,
  predictor ENUM('traffic','hvac') NOT NULL,
  controls JSON NOT NULL,
  note VARCHAR(350) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE diagnostics (
  id INT PRIMARY KEY AUTO_INCREMENT,
  method_id INT NOT NULL,
  title VARCHAR(80) UNIQUE NOT NULL,
  owner_id INT NOT NULL,
  state ENUM('queued','complete','blocked','failed') NOT NULL DEFAULT 'queued',
  fingerprint CHAR(64) NOT NULL,
  snapshot JSON NOT NULL,
  result JSON,
  publication JSON,
  reviewer_id INT,
  decision VARCHAR(500),
  reviewed_at TIMESTAMP NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  finished_at TIMESTAMP NULL,
  INDEX (state, id),
  FOREIGN KEY (method_id) REFERENCES methods(id),
  FOREIGN KEY (owner_id) REFERENCES accounts(id),
  FOREIGN KEY (reviewer_id) REFERENCES accounts(id)
);
CREATE TABLE intakes (
  id INT PRIMARY KEY AUTO_INCREMENT,
  intake_key VARCHAR(64) UNIQUE NOT NULL,
  source_studio VARCHAR(48) NOT NULL,
  title VARCHAR(80) NOT NULL,
  owner_id INT NOT NULL,
  method_id INT,
  method_version VARCHAR(32) NOT NULL,
  algorithm VARCHAR(48) NOT NULL,
  fingerprint CHAR(64) NOT NULL,
  original JSON NOT NULL,
  claim JSON NOT NULL,
  state ENUM('queued','complete','failed') NOT NULL DEFAULT 'queued',
  outcome ENUM('supported','coefficient_mismatch','missing_samples','incomputable','unsupported_algorithm') NULL,
  result JSON,
  conflicts JSON,
  evidence JSON,
  publication JSON,
  attempts INT NOT NULL DEFAULT 0,
  reviewer_id INT,
  decision VARCHAR(500),
  reviewed_at TIMESTAMP NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  finished_at TIMESTAMP NULL,
  INDEX (state, id),
  FOREIGN KEY (owner_id) REFERENCES accounts(id),
  FOREIGN KEY (method_id) REFERENCES methods(id),
  FOREIGN KEY (reviewer_id) REFERENCES accounts(id)
);
CREATE TABLE audit (
  id INT PRIMARY KEY AUTO_INCREMENT,
  actor_id INT,
  action VARCHAR(40) NOT NULL,
  subject VARCHAR(64) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (actor_id) REFERENCES accounts(id)
);
