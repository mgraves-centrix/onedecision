"""SQLite access and schema.

One connection factory, one schema, no ORM. The audit table is append-only and
enforced as such by triggers, not by convention.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import settings

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- synthetic
-- Synthetic business systems. See app/adapters/. Not production data.

CREATE TABLE IF NOT EXISTS kit_catalog (
    sku                 TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    category            TEXT NOT NULL,
    declared_value_usd  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS kit_components (
    sku                 TEXT NOT NULL,
    component_id        TEXT NOT NULL,
    name                TEXT NOT NULL,
    serialized          INTEGER NOT NULL,
    safety_critical     INTEGER NOT NULL,
    essential           INTEGER NOT NULL,
    PRIMARY KEY (sku, component_id),
    FOREIGN KEY (sku) REFERENCES kit_catalog(sku)
);

CREATE TABLE IF NOT EXISTS parts_catalog (
    component_id        TEXT PRIMARY KEY,
    replacement_cost_usd REAL,
    stock_status        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS return_cases (
    case_id             TEXT PRIMARY KEY,
    order_id            TEXT NOT NULL,
    customer_ref        TEXT NOT NULL,
    sku                 TEXT NOT NULL,
    expected_serial     TEXT NOT NULL,
    received_serial     TEXT,
    received_components TEXT NOT NULL,   -- JSON list of component_id
    inspection_evidence TEXT NOT NULL,   -- JSON object
    new_damage_present  INTEGER NOT NULL,
    inspector_notes     TEXT NOT NULL DEFAULT '',
    received_at         TEXT NOT NULL,
    expected_label      TEXT NOT NULL,   -- ground truth for evaluation
    scenario_note       TEXT NOT NULL DEFAULT '',
    is_historical       INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (sku) REFERENCES kit_catalog(sku)
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

-- ------------------------------------------------------------- OneDecision

CREATE TABLE IF NOT EXISTS exceptions (
    exception_id        TEXT PRIMARY KEY,
    case_id             TEXT NOT NULL,
    trace_id            TEXT NOT NULL,
    status              TEXT NOT NULL,
    event_key           TEXT NOT NULL UNIQUE,   -- dedupes duplicate events
    summary             TEXT NOT NULL DEFAULT '',
    escalation_reasons  TEXT NOT NULL DEFAULT '[]',
    applied_policy_id   TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES return_cases(case_id)
);

CREATE TABLE IF NOT EXISTS decision_cards (
    decision_card_id    TEXT PRIMARY KEY,
    exception_id        TEXT NOT NULL,
    payload             TEXT NOT NULL,   -- JSON DecisionCard
    outcome             TEXT,            -- approve_and_teach | reject | revise
    decided_by          TEXT,
    decided_at          TEXT,
    created_at          TEXT NOT NULL,
    FOREIGN KEY (exception_id) REFERENCES exceptions(exception_id)
);

CREATE TABLE IF NOT EXISTS policies (
    policy_id           TEXT PRIMARY KEY,
    family              TEXT NOT NULL,
    version             INTEGER NOT NULL,
    status              TEXT NOT NULL,   -- candidate | active | retired | rejected
    definition          TEXT NOT NULL,   -- JSON PolicyDefinition
    origin_case_id      TEXT,
    origin_decision_id  TEXT,
    replay_report       TEXT,            -- JSON ReplayReport
    created_at          TEXT NOT NULL,
    activated_at        TEXT,
    activated_by        TEXT,
    retired_at          TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    seq                 INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id            TEXT NOT NULL UNIQUE,
    trace_id            TEXT NOT NULL,
    event_type          TEXT NOT NULL,
    case_id             TEXT,
    exception_id        TEXT,
    policy_id           TEXT,
    actor               TEXT NOT NULL,
    payload             TEXT NOT NULL,   -- JSON
    prev_hash           TEXT NOT NULL,
    entry_hash          TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_trace ON audit_log(trace_id);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_log(case_id);
CREATE INDEX IF NOT EXISTS idx_policy_status ON policies(status);

-- The audit log is append-only. These triggers make that a property of the
-- database rather than a promise in a code comment.
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
"""


def db_path() -> Path:
    return settings.db_path


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = Path(path) if path is not None else db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    # Strands executes tools on a worker thread, so the connection must be
    # usable across threads. CPython's sqlite3 is built in serialized mode
    # (sqlite3.threadsafety == 3), which makes this safe at the driver level.
    conn = sqlite3.connect(
        target, isolation_level=None, timeout=15.0, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: Path | None = None) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()


@contextmanager
def session(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        conn.execute("BEGIN")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


@contextmanager
def read_only(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


def drop_all(path: Path | None = None) -> None:
    """Used only by `make seed --reset` and by the test fixtures."""
    target = Path(path) if path is not None else db_path()
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(target) + suffix)
        if candidate.exists():
            candidate.unlink()
