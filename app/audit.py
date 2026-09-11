"""Append-only, hash-chained audit log.

Every entry carries the hash of the previous entry, so the chain can be verified
and any tampering shows up as a break. `UPDATE` and `DELETE` are rejected by
SQLite triggers (see `app/db.py`), not by convention.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.db import Connection

GENESIS_HASH = "0" * 64


class AuditEventType:
    EVENT_RECEIVED = "event.received"
    EVENT_DUPLICATE = "event.duplicate_suppressed"
    INVESTIGATION_STARTED = "investigation.started"
    TOOL_CALLED = "tool.called"
    TOOL_FAILED = "tool.failed"
    INVESTIGATION_COMPLETED = "investigation.completed"
    AGENT_RUN = "agent.run"
    RECONCILIATION_MISMATCH = "investigation.reconciliation_mismatch"
    GUARDRAIL_BLOCKED = "guardrail.blocked"
    POLICY_MATCHED = "policy.matched"
    POLICY_NOT_FOUND = "policy.not_found"
    POLICY_CONFLICT = "policy.conflict"
    DECISION_CARD_CREATED = "decision.card_created"
    DECISION_RECORDED = "decision.recorded"
    POLICY_PROPOSED = "policy.proposed"
    POLICY_REVISED = "policy.revised"
    POLICY_SUPERSEDED = "policy.superseded"
    POLICY_REJECTED_SCHEMA = "policy.rejected_schema"
    POLICY_REPLAY_RUN = "policy.replay_run"
    POLICY_ACTIVATION_BLOCKED = "policy.activation_blocked"
    POLICY_ACTIVATED = "policy.activated"
    POLICY_RETIRED = "policy.retired"
    ACTION_EXECUTED = "action.executed"
    ACTION_DUPLICATE = "action.duplicate_suppressed"
    ACTION_FAILED = "action.failed"
    VERIFICATION_PASSED = "verification.passed"
    VERIFICATION_FAILED = "verification.failed"
    EXCEPTION_RESOLVED = "exception.resolved"
    EXCEPTION_ESCALATED = "exception.escalated"
    DEMO_RESET = "demo.reset"


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    entry_id: str
    trace_id: str
    event_type: str
    case_id: str | None
    exception_id: str | None
    policy_id: str | None
    actor: str
    payload: dict[str, Any]
    prev_hash: str
    entry_hash: str
    created_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(
    *,
    entry_id: str,
    trace_id: str,
    event_type: str,
    actor: str,
    payload: dict[str, Any],
    prev_hash: str,
    created_at: str,
) -> str:
    material = "|".join(
        [entry_id, trace_id, event_type, actor, _canonical(payload), prev_hash, created_at]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _head_hash(conn: "Connection") -> str:
    row = conn.execute("SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
    return row["entry_hash"] if row else GENESIS_HASH


def record(
    conn: "Connection",
    *,
    trace_id: str,
    event_type: str,
    actor: str,
    payload: dict[str, Any] | None = None,
    case_id: str | None = None,
    exception_id: str | None = None,
    policy_id: str | None = None,
) -> AuditEntry:
    """Append one entry. The only way to write to the audit log."""
    payload = payload or {}
    # Appending is read-head-then-insert, which is a race with concurrent
    # writers. The lock is held until this transaction ends; `prev_hash UNIQUE`
    # is the backstop if a writer ever reaches the insert without it.
    conn.lock_audit_chain()
    entry_id = f"aud_{uuid.uuid4().hex[:16]}"
    created_at = _now()
    prev_hash = _head_hash(conn)
    entry_hash = compute_hash(
        entry_id=entry_id,
        trace_id=trace_id,
        event_type=event_type,
        actor=actor,
        payload=payload,
        prev_hash=prev_hash,
        created_at=created_at,
    )
    cur = conn.execute(
        """
        INSERT INTO audit_log (entry_id, trace_id, event_type, case_id, exception_id,
                               policy_id, actor, payload, prev_hash, entry_hash, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING seq
        """,
        (
            entry_id,
            trace_id,
            event_type,
            case_id,
            exception_id,
            policy_id,
            actor,
            _canonical(payload),
            prev_hash,
            entry_hash,
            created_at,
        ),
    )
    inserted = cur.fetchone()
    return AuditEntry(
        seq=int(inserted["seq"]) if inserted else 0,
        entry_id=entry_id,
        trace_id=trace_id,
        event_type=event_type,
        case_id=case_id,
        exception_id=exception_id,
        policy_id=policy_id,
        actor=actor,
        payload=payload,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
        created_at=created_at,
    )


def _row_to_entry(row: dict) -> AuditEntry:
    return AuditEntry(
        seq=row["seq"],
        entry_id=row["entry_id"],
        trace_id=row["trace_id"],
        event_type=row["event_type"],
        case_id=row["case_id"],
        exception_id=row["exception_id"],
        policy_id=row["policy_id"],
        actor=row["actor"],
        payload=json.loads(row["payload"]),
        prev_hash=row["prev_hash"],
        entry_hash=row["entry_hash"],
        created_at=row["created_at"],
    )


def read_all(conn: "Connection", limit: int = 500) -> list[AuditEntry]:
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY seq DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_row_to_entry(r) for r in rows]


def read_recent(
    conn: "Connection", *, limit: int = 25, since: str | None = None
) -> list[AuditEntry]:
    """Newest first, optionally only entries recorded at or after `since`."""
    if since is None:
        return read_all(conn, limit=limit)
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE created_at >= ? ORDER BY seq DESC LIMIT ?",
        (since, limit),
    ).fetchall()
    return [_row_to_entry(r) for r in rows]


def read_for_case(conn: "Connection", case_id: str) -> list[AuditEntry]:
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE case_id = ? ORDER BY seq ASC", (case_id,)
    ).fetchall()
    return [_row_to_entry(r) for r in rows]


def read_for_trace(conn: "Connection", trace_id: str) -> list[AuditEntry]:
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE trace_id = ? ORDER BY seq ASC", (trace_id,)
    ).fetchall()
    return [_row_to_entry(r) for r in rows]


@dataclass(frozen=True)
class ChainVerification:
    ok: bool
    entries_checked: int
    broken_at: int | None = None
    detail: str = ""


def verify_chain(conn: "Connection") -> ChainVerification:
    """Recompute the hash chain end to end."""
    rows = conn.execute("SELECT * FROM audit_log ORDER BY seq ASC").fetchall()
    prev = GENESIS_HASH
    for row in rows:
        if row["prev_hash"] != prev:
            return ChainVerification(False, len(rows), row["seq"], "prev_hash does not match chain head")
        expected = compute_hash(
            entry_id=row["entry_id"],
            trace_id=row["trace_id"],
            event_type=row["event_type"],
            actor=row["actor"],
            payload=json.loads(row["payload"]),
            prev_hash=row["prev_hash"],
            created_at=row["created_at"],
        )
        if expected != row["entry_hash"]:
            return ChainVerification(False, len(rows), row["seq"], "entry_hash does not match content")
        prev = row["entry_hash"]
    return ChainVerification(True, len(rows), None, "chain intact")
