-- A second domain on the same machinery: accounts-payable invoice variance.
--
-- Two changes. First, the governance tables stop belonging to returns: an
-- exception carries the family that raised it, and its case_id no longer points
-- at return_cases, because an invoice is not a return case. SQLite cannot drop a
-- constraint, so both tables are rebuilt -- children first, so the foreign key
-- from decision_cards follows the new table rather than the old one, and no
-- implicit delete ever runs against a table that still has children.
--
-- Second, the AP domain's own systems of record. The shared tables (policies,
-- decision_cards, audit_log) are untouched by it.
CREATE TABLE exceptions_v2 (
    exception_id        TEXT PRIMARY KEY,
    case_id             TEXT NOT NULL,
    family              TEXT NOT NULL DEFAULT 'returns.missing_accessory',
    trace_id            TEXT NOT NULL,
    status              TEXT NOT NULL,
    event_key           TEXT NOT NULL UNIQUE,
    summary             TEXT NOT NULL DEFAULT '',
    escalation_reasons  TEXT NOT NULL DEFAULT '[]',
    applied_policy_id   TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

INSERT INTO exceptions_v2 (exception_id, case_id, family, trace_id, status, event_key,
                           summary, escalation_reasons, applied_policy_id, created_at, updated_at)
SELECT exception_id, case_id, 'returns.missing_accessory', trace_id, status, event_key,
       summary, escalation_reasons, applied_policy_id, created_at, updated_at
  FROM exceptions;

CREATE TABLE decision_cards_v2 (
    decision_card_id    TEXT PRIMARY KEY,
    exception_id        TEXT NOT NULL REFERENCES exceptions_v2(exception_id),
    payload             TEXT NOT NULL,
    outcome             TEXT,
    decided_by          TEXT,
    decided_at          TEXT,
    created_at          TEXT NOT NULL
);

INSERT INTO decision_cards_v2 (decision_card_id, exception_id, payload, outcome,
                               decided_by, decided_at, created_at)
SELECT decision_card_id, exception_id, payload, outcome, decided_by, decided_at, created_at
  FROM decision_cards;

DROP TABLE decision_cards;
DROP TABLE exceptions;

ALTER TABLE exceptions_v2 RENAME TO exceptions;
ALTER TABLE decision_cards_v2 RENAME TO decision_cards;

CREATE INDEX IF NOT EXISTS idx_exceptions_case ON exceptions(case_id);
CREATE INDEX IF NOT EXISTS idx_exceptions_policy ON exceptions(applied_policy_id);
CREATE INDEX IF NOT EXISTS idx_exceptions_family ON exceptions(family);

CREATE TABLE IF NOT EXISTS ap_vendors (
    vendor_id           TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    risk_tier           TEXT NOT NULL,
    on_hold             INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ap_invoices (
    invoice_id          TEXT PRIMARY KEY,
    vendor_id           TEXT NOT NULL REFERENCES ap_vendors(vendor_id),
    vendor_invoice_no   TEXT NOT NULL,
    po_number           TEXT,
    po_total_usd        REAL,
    received_total_usd  REAL,
    invoice_total_usd   REAL NOT NULL,
    tax_amount_usd      REAL,
    expected_tax_usd    REAL,
    currency            TEXT NOT NULL DEFAULT 'USD',
    evidence            TEXT NOT NULL DEFAULT '{}',
    submitter_notes     TEXT NOT NULL DEFAULT '',
    received_at         TEXT NOT NULL,
    expected_label      TEXT NOT NULL,
    scenario_note       TEXT NOT NULL DEFAULT '',
    is_historical       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ap_adjustments (
    adjustment_id       TEXT PRIMARY KEY,
    invoice_id          TEXT NOT NULL,
    gl_account          TEXT NOT NULL,
    amount_usd          REAL NOT NULL,
    status              TEXT NOT NULL,
    idempotency_key     TEXT NOT NULL UNIQUE,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ap_payment_releases (
    invoice_id          TEXT PRIMARY KEY,
    release_type        TEXT NOT NULL,
    status              TEXT NOT NULL,
    idempotency_key     TEXT NOT NULL UNIQUE,
    released_at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ap_invoices_vendor ON ap_invoices(vendor_id);
CREATE INDEX IF NOT EXISTS idx_ap_adjustments_invoice ON ap_adjustments(invoice_id);
