"""SYNTHETIC ADAPTER — warehouse management system (state-changing).

Every write takes an idempotency key. Repeating a call with the same key is a
no-op that returns the original result, so a duplicate event or a retried
execution can never create a second work order.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.adapters import SYNTHETIC_NOTICE
from app.adapters.returns_system import AdapterError

ALLOWED_DISPOSITIONS = frozenset({"PARTS_HOLD"})
ALLOWED_WORK_ORDER_TYPES = frozenset({"REPLACEMENT_PARTS"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def set_disposition(
    conn: sqlite3.Connection, *, case_id: str, disposition: str, idempotency_key: str
) -> dict[str, Any]:
    if disposition not in ALLOWED_DISPOSITIONS:
        raise AdapterError(
            f"disposition '{disposition}' is not permitted for automated action"
        )
    existing = conn.execute(
        "SELECT * FROM dispositions WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    if existing is not None:
        return {
            "_source": SYNTHETIC_NOTICE,
            "case_id": existing["case_id"],
            "disposition": existing["disposition"],
            "duplicate_suppressed": True,
            "set_at": existing["set_at"],
        }
    conn.execute(
        """
        INSERT INTO dispositions (case_id, disposition, idempotency_key, set_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(case_id) DO UPDATE SET
            disposition = excluded.disposition,
            idempotency_key = excluded.idempotency_key,
            set_at = excluded.set_at
        """,
        (case_id, disposition, idempotency_key, _now()),
    )
    return {
        "_source": SYNTHETIC_NOTICE,
        "case_id": case_id,
        "disposition": disposition,
        "duplicate_suppressed": False,
        "set_at": _now(),
    }


def create_work_order(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    work_order_type: str,
    component_id: str,
    cost_usd: float,
    max_cost_usd: float,
    idempotency_key: str,
) -> dict[str, Any]:
    if work_order_type not in ALLOWED_WORK_ORDER_TYPES:
        raise AdapterError(f"work order type '{work_order_type}' is not permitted")
    if cost_usd > max_cost_usd:
        # Second enforcement of the spend cap, at the point of action.
        raise AdapterError(
            f"work order cost ${cost_usd:.2f} exceeds the authorised cap ${max_cost_usd:.2f}"
        )
    existing = conn.execute(
        "SELECT * FROM work_orders WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    if existing is not None:
        return {
            "_source": SYNTHETIC_NOTICE,
            "work_order_id": existing["work_order_id"],
            "duplicate_suppressed": True,
            "status": existing["status"],
        }
    work_order_id = f"WO-{idempotency_key[-10:].upper()}"
    conn.execute(
        """
        INSERT INTO work_orders (work_order_id, case_id, work_order_type, component_id,
                                 cost_usd, status, idempotency_key, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            work_order_id,
            case_id,
            work_order_type,
            component_id,
            cost_usd,
            "OPEN",
            idempotency_key,
            _now(),
        ),
    )
    return {
        "_source": SYNTHETIC_NOTICE,
        "work_order_id": work_order_id,
        "duplicate_suppressed": False,
        "status": "OPEN",
    }


def get_disposition(conn: sqlite3.Connection, case_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM dispositions WHERE case_id = ?", (case_id,)).fetchone()
    return dict(row) if row else None


def get_work_orders(conn: sqlite3.Connection, case_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM work_orders WHERE case_id = ? ORDER BY created_at", (case_id,)
    ).fetchall()
    return [dict(r) for r in rows]
