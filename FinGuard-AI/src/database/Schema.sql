-- FinGuard AI schema (PostgreSQL)
-- Run order matters: parent tables first.

DROP TABLE IF EXISTS audit_logs, agent_tool_calls, agent_runs, investigations,
    anomaly_events, risk_predictions, risk_policies, transactions, customers CASCADE;

CREATE TABLE customers (
    customer_id      VARCHAR(20) PRIMARY KEY,
    age_group        VARCHAR(10),
    home_country     CHAR(2),
    account_age_days INTEGER,
    account_status   VARCHAR(20)
);

CREATE TABLE transactions (
    transaction_id    VARCHAR(20) PRIMARY KEY,
    customer_id       VARCHAR(20) NOT NULL REFERENCES customers(customer_id),
    txn_timestamp     TIMESTAMP NOT NULL,
    amount            NUMERIC(12,2) NOT NULL CHECK (amount >= 0),
    merchant          VARCHAR(30),
    merchant_category VARCHAR(30),
    country           CHAR(2),
    home_country      CHAR(2),
    is_international  SMALLINT,
    channel           VARCHAR(20),
    device_type       VARCHAR(10),
    is_fraud          SMALLINT NOT NULL CHECK (is_fraud IN (0, 1))
);

CREATE INDEX idx_txn_timestamp ON transactions(txn_timestamp);
CREATE INDEX idx_txn_customer  ON transactions(customer_id);
CREATE INDEX idx_txn_fraud     ON transactions(is_fraud);

CREATE TABLE risk_predictions (
    prediction_id     SERIAL PRIMARY KEY,
    transaction_id    VARCHAR(20) NOT NULL REFERENCES transactions(transaction_id),
    fraud_probability NUMERIC(5,4) NOT NULL,
    risk_band         VARCHAR(10),
    model_version     VARCHAR(30),
    created_at        TIMESTAMP DEFAULT NOW()
);

CREATE TABLE anomaly_events (
    event_id       SERIAL PRIMARY KEY,
    transaction_id VARCHAR(20) REFERENCES transactions(transaction_id),
    anomaly_score  NUMERIC(8,4),
    reason         TEXT,
    created_at     TIMESTAMP DEFAULT NOW()
);

CREATE TABLE investigations (
    investigation_id VARCHAR(20) PRIMARY KEY,
    question         TEXT,
    status           VARCHAR(20) DEFAULT 'pending',
    summary          TEXT,
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE agent_runs (
    run_id             SERIAL PRIMARY KEY,
    investigation_id   VARCHAR(20) REFERENCES investigations(investigation_id),
    agent_name         VARCHAR(50) NOT NULL,
    status             VARCHAR(20),
    execution_time_ms  INTEGER,
    created_at         TIMESTAMP DEFAULT NOW()
);

CREATE TABLE agent_tool_calls (
    call_id    SERIAL PRIMARY KEY,
    run_id     INTEGER REFERENCES agent_runs(run_id),
    tool_name  VARCHAR(50) NOT NULL,
    input_hash VARCHAR(64),
    status     VARCHAR(20),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE risk_policies (
    policy_id   SERIAL PRIMARY KEY,
    document_id VARCHAR(50) NOT NULL,
    title       VARCHAR(200),
    version     VARCHAR(20),
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE audit_logs (
    log_id     SERIAL PRIMARY KEY,
    actor      VARCHAR(50) NOT NULL,
    action     VARCHAR(100) NOT NULL,
    details    TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
