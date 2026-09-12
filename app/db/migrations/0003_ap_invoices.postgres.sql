-- A second domain on the same machinery: accounts-payable invoice variance.
--
-- Two changes. First, the governance tables stop belonging to returns: an
-- exception carries the family that raised it, and its case_id no longer points
-- at return_cases, because an invoice is not a return case. PostgreSQL can drop
-- the constraint in place; the SQLite migration rebuilds the table for the same
-- result.
--
-- Second, the AP domain's own systems of record. The shared tables (policies,
-- decision_cards, audit_log) are untouched by it.
ALTER TABLE exceptions DROP CONSTRAINT IF EXISTS exceptions_case_id_fkey;
ALTER TABLE exceptions ADD COLUMN IF NOT EXISTS family TEXT NOT NULL
    DEFAULT 'returns.missing_accessory';

CREATE INDEX IF NOT EXISTS idx_exceptions_family ON exceptions(family);

CREATE TABLE IF NOT EXISTS ap_vendors (
    vendor_id           TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    risk_tier           TEXT NOT NULL,
    on_hold             BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS ap_invoices (
    invoice_id          TEXT PRIMARY KEY,
    vendor_id           TEXT NOT NULL REFERENCES ap_vendors(vendor_id),
    vendor_invoice_no   TEXT NOT NULL,
    po_number           TEXT,
    po_total_usd        NUMERIC(12, 2),
    received_total_usd  NUMERIC(12, 2),
    invoice_total_usd   NUMERIC(12, 2) NOT NULL,
    tax_amount_usd      NUMERIC(12, 2),
    expected_tax_usd    NUMERIC(12, 2),
    currency            TEXT NOT NULL DEFAULT 'USD',
    evidence            TEXT NOT NULL DEFAULT '{}',
    submitter_notes     TEXT NOT NULL DEFAULT '',
    received_at         TEXT NOT NULL,
    expected_label      TEXT NOT NULL,
    scenario_note       TEXT NOT NULL DEFAULT '',
    is_historical       BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS ap_adjustments (
    adjustment_id       TEXT PRIMARY KEY,
    invoice_id          TEXT NOT NULL,
    gl_account          TEXT NOT NULL,
    amount_usd          NUMERIC(12, 2) NOT NULL,
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
