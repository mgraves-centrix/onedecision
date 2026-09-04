-- Baseline schema (SQLite). Zero-setup local demo backend.
-- The PostgreSQL twin lives in 0001_baseline.postgres.sql and must stay
-- semantically identical; tests run the whole suite against both.

CREATE TABLE IF NOT EXISTS kit_catalog (
    sku                 TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    category            TEXT NOT NULL,
    declared_value_usd  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS kit_components (
    sku                 TEXT NOT NULL REFERENCES kit_catalog(sku),
    component_id        TEXT NOT NULL,
    name                TEXT NOT NULL,
    serialized          INTEGER NOT NULL,
    safety_critical     INTEGER NOT NULL,
    essential           INTEGER NOT NULL,
    PRIMARY KEY (sku, component_id)
);

CREATE TABLE IF NOT EXISTS parts_catalog (
    component_id            TEXT PRIMARY KEY,
    replacement_cost_usd    REAL,
    stock_status            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS return_cases (
    case_id             TEXT PRIMARY KEY,
    order_id            TEXT NOT NULL,
    customer_ref        TEXT NOT NULL,
    sku                 TEXT NOT NULL REFERENCES kit_catalog(sku),
    expected_serial     TEXT NOT NULL,
    received_serial     TEXT,
    received_components TEXT NOT NULL,
    inspection_evidence TEXT NOT NULL,
    new_damage_present  INTEGER NOT NULL,
    inspector_notes     TEXT NOT NULL DEFAULT '',
    received_at         TEXT NOT NULL,
    expected_label      TEXT NOT NULL,
    scenario_note       TEXT NOT NULL DEFAULT '',
    is_historical       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS work_orders (
    work_order_id       TEXT PRIMARY KEY,
    case_id             TEXT NOT NULL,
    work_order_type     TEXT NOT NULL,
    component_id        TEXT NOT NULL,
    cost_usd            REAL NOT NULL,
    status              TEXT NOT NULL,
    idempotency_key     TEXT NOT NULL UNIQUE,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dispositions (
    case_id             TEXT PRIMARY KEY,
    disposition         TEXT NOT NULL,
    idempotency_key     TEXT NOT NULL UNIQUE,
    set_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exceptions (
    exception_id        TEXT PRIMARY KEY,
    case_id             TEXT NOT NULL REFERENCES return_cases(case_id),
    trace_id            TEXT NOT NULL,
    status              TEXT NOT NULL,
    event_key           TEXT NOT NULL UNIQUE,
    summary             TEXT NOT NULL DEFAULT '',
    escalation_reasons  TEXT NOT NULL DEFAULT '[]',
    applied_policy_id   TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_cards (
    decision_card_id    TEXT PRIMARY KEY,
    exception_id        TEXT NOT NULL REFERENCES exceptions(exception_id),
    payload             TEXT NOT NULL,
    outcome             TEXT,
    decided_by          TEXT,
    decided_at          TEXT,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policies (
    policy_id           TEXT PRIMARY KEY,
    family              TEXT NOT NULL,
    version             INTEGER NOT NULL,
    status              TEXT NOT NULL,
    definition          TEXT NOT NULL,
    origin_case_id      TEXT,
    origin_decision_id  TEXT,
    replay_report       TEXT,
    created_at          TEXT NOT NULL,
    activated_at        TEXT,
    activated_by        TEXT,
    retired_at          TEXT,
    UNIQUE (family, version)
);

-- `created_at` is hashed content, so it stays an exact string on both backends.
-- `prev_hash` is UNIQUE: two entries cannot claim the same predecessor, so a
-- concurrent fork of the chain fails as a constraint violation rather than
-- corrupting the log silently.
CREATE TABLE IF NOT EXISTS audit_log (
    seq                 INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id            TEXT NOT NULL UNIQUE,
    trace_id            TEXT NOT NULL,
    event_type          TEXT NOT NULL,
    case_id             TEXT,
    exception_id        TEXT,
    policy_id           TEXT,
    actor               TEXT NOT NULL,
    payload             TEXT NOT NULL,
    prev_hash           TEXT NOT NULL UNIQUE,
    entry_hash          TEXT NOT NULL UNIQUE,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_trace ON audit_log(trace_id);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_log(case_id);
CREATE INDEX IF NOT EXISTS idx_policy_status ON policies(status);
CREATE INDEX IF NOT EXISTS idx_exceptions_case ON exceptions(case_id);
CREATE INDEX IF NOT EXISTS idx_exceptions_policy ON exceptions(applied_policy_id);
CREATE INDEX IF NOT EXISTS idx_work_orders_case ON work_orders(case_id);

CREATE TRIGGER IF NOT EXISTS audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: UPDATE rejected');
END;

CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: DELETE rejected');
END;
