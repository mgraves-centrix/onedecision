"""Policy persistence and the activation gate.

The activation gate is the single most important function in the project:
`activate_policy` is the only path from *candidate* to *active*, it requires a
human approval token, and it refuses without a passing replay report.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app import audit
from app.audit import AuditEventType
from app.config import settings
from app.domain import PolicyStatus
from app.policy.schema import POLICY_FAMILY, PolicyDefinition, PolicyValidationError, validate_policy_payload


class ActivationDenied(Exception):
    """Raised when an activation attempt fails a gate. Never bypassable."""


@dataclass(frozen=True)
class PolicyRecord:
    policy_id: str
    family: str
    version: int
    status: str
    definition: PolicyDefinition
    origin_case_id: str | None
    origin_decision_id: str | None
    replay_report: dict[str, Any] | None
    created_at: str
    activated_at: str | None
    activated_by: str | None
    retired_at: str | None

    @property
    def label(self) -> str:
        return f"{self.family}@v{self.version}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _row(row: sqlite3.Row) -> PolicyRecord:
    return PolicyRecord(
        policy_id=row["policy_id"],
        family=row["family"],
        version=row["version"],
        status=row["status"],
        definition=PolicyDefinition.model_validate_json(row["definition"]),
        origin_case_id=row["origin_case_id"],
        origin_decision_id=row["origin_decision_id"],
        replay_report=json.loads(row["replay_report"]) if row["replay_report"] else None,
        created_at=row["created_at"],
        activated_at=row["activated_at"],
        activated_by=row["activated_by"],
        retired_at=row["retired_at"],
    )


def next_version(conn: sqlite3.Connection, family: str = POLICY_FAMILY) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS v FROM policies WHERE family = ?", (family,)
    ).fetchone()
    return int(row["v"]) + 1


def create_candidate(
    conn: sqlite3.Connection,
    *,
    payload: dict[str, Any],
    trace_id: str,
    origin_case_id: str | None = None,
    origin_decision_id: str | None = None,
    actor: str = "agent",
) -> PolicyRecord:
    """Validate an untrusted proposal and store it as a **candidate**.

    A candidate can do nothing. It is inert until replay passes and a human
    activates it.
    """
    try:
        definition = validate_policy_payload(payload)
    except PolicyValidationError as exc:
        audit.record(
            conn,
            trace_id=trace_id,
            event_type=AuditEventType.POLICY_REJECTED_SCHEMA,
            actor=actor,
            case_id=origin_case_id,
            payload={"errors": exc.errors},
        )
        raise

    version = next_version(conn, definition.family)
    policy_id = f"pol_{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO policies (policy_id, family, version, status, definition,
                              origin_case_id, origin_decision_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            policy_id,
            definition.family,
            version,
            PolicyStatus.CANDIDATE,
            definition.model_dump_json(),
            origin_case_id,
            origin_decision_id,
            _now(),
        ),
    )
    audit.record(
        conn,
        trace_id=trace_id,
        event_type=AuditEventType.POLICY_PROPOSED,
        actor=actor,
        case_id=origin_case_id,
        policy_id=policy_id,
        payload={
            "version": version,
            "name": definition.name,
            "conditions": definition.condition_summary(),
            "actions": definition.action_summary(),
            "status": PolicyStatus.CANDIDATE.value,
        },
    )
    return get(conn, policy_id)


def get(conn: sqlite3.Connection, policy_id: str) -> PolicyRecord:
    row = conn.execute("SELECT * FROM policies WHERE policy_id = ?", (policy_id,)).fetchone()
    if row is None:
        raise KeyError(f"policy '{policy_id}' not found")
    return _row(row)


def list_all(conn: sqlite3.Connection) -> list[PolicyRecord]:
    rows = conn.execute("SELECT * FROM policies ORDER BY version DESC").fetchall()
    return [_row(r) for r in rows]


def list_active(conn: sqlite3.Connection) -> list[PolicyRecord]:
    rows = conn.execute(
        "SELECT * FROM policies WHERE status = ? ORDER BY version ASC", (PolicyStatus.ACTIVE,)
    ).fetchall()
    return [_row(r) for r in rows]


def attach_replay_report(
    conn: sqlite3.Connection, policy_id: str, report: dict[str, Any], *, trace_id: str
) -> None:
    conn.execute(
        "UPDATE policies SET replay_report = ? WHERE policy_id = ?",
        (json.dumps(report, default=str), policy_id),
    )
    audit.record(
        conn,
        trace_id=trace_id,
        event_type=AuditEventType.POLICY_REPLAY_RUN,
        actor="system",
        policy_id=policy_id,
        payload={
            "passed": report.get("passed"),
            "cases_replayed": report.get("cases_replayed"),
            "false_automatic_actions": report.get("false_automatic_actions"),
            "correct_auto_resolutions": report.get("correct_auto_resolutions"),
            "correct_escalations": report.get("correct_escalations"),
        },
    )


def activate(
    conn: sqlite3.Connection,
    policy_id: str,
    *,
    approval_token: str,
    activated_by: str,
    trace_id: str,
) -> PolicyRecord:
    """THE ACTIVATION GATE.

    Three conditions, all required, none skippable:
      1. a valid human approval token,
      2. the policy is a validated candidate,
      3. a replay report exists and passed.
    """
    record = get(conn, policy_id)

    def deny(reason: str) -> ActivationDenied:
        audit.record(
            conn,
            trace_id=trace_id,
            event_type=AuditEventType.POLICY_ACTIVATION_BLOCKED,
            actor=activated_by,
            policy_id=policy_id,
            payload={"reason": reason},
        )
        return ActivationDenied(reason)

    if not approval_token or approval_token != settings.approval_token:
        raise deny("invalid or missing approval token")

    if record.status != PolicyStatus.CANDIDATE:
        raise deny(f"policy is '{record.status}', only a candidate may be activated")

    if not record.replay_report:
        raise deny("policy has no replay report; run replay before activation")

    if not record.replay_report.get("passed"):
        failures = record.replay_report.get("failures", [])
        raise deny(f"replay did not pass ({len(failures)} failing case(s))")

    # Supersede any active policy in the same family. One active version at a
    # time keeps "conflicting policies" a testable condition rather than a
    # surprise.
    superseded = [p.policy_id for p in list_active(conn) if p.family == record.family]
    for old_id in superseded:
        conn.execute(
            "UPDATE policies SET status = ?, retired_at = ? WHERE policy_id = ?",
            (PolicyStatus.RETIRED, _now(), old_id),
        )
        audit.record(
            conn,
            trace_id=trace_id,
            event_type=AuditEventType.POLICY_RETIRED,
            actor=activated_by,
            policy_id=old_id,
            payload={"superseded_by": policy_id},
        )

    conn.execute(
        "UPDATE policies SET status = ?, activated_at = ?, activated_by = ? WHERE policy_id = ?",
        (PolicyStatus.ACTIVE, _now(), activated_by, policy_id),
    )
    audit.record(
        conn,
        trace_id=trace_id,
        event_type=AuditEventType.POLICY_ACTIVATED,
        actor=activated_by,
        policy_id=policy_id,
        payload={
            "version": record.version,
            "name": record.definition.name,
            "superseded": superseded,
            "replay_cases": record.replay_report.get("cases_replayed"),
        },
    )
    return get(conn, policy_id)


def reject(
    conn: sqlite3.Connection, policy_id: str, *, actor: str, trace_id: str, reason: str = ""
) -> PolicyRecord:
    conn.execute(
        "UPDATE policies SET status = ? WHERE policy_id = ?", (PolicyStatus.REJECTED, policy_id)
    )
    audit.record(
        conn,
        trace_id=trace_id,
        event_type=AuditEventType.POLICY_ACTIVATION_BLOCKED,
        actor=actor,
        policy_id=policy_id,
        payload={"reason": reason or "rejected by human reviewer"},
    )
    return get(conn, policy_id)


def cases_handled(conn: sqlite3.Connection, policy_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT case_id FROM exceptions WHERE applied_policy_id = ? ORDER BY updated_at",
        (policy_id,),
    ).fetchall()
    return [r["case_id"] for r in rows]
