"""SYNTHETIC ADAPTER — replacement parts catalog (read-only)."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.adapters import SYNTHETIC_NOTICE
from app.adapters.returns_system import AdapterError

# Component ids that deliberately make the synthetic catalog fail, so the
# tool-failure escalation path is exercised rather than assumed.
FAILING_COMPONENT_IDS = frozenset({"CMP-FAULT-SIM"})


def lookup_replacement_cost(conn: sqlite3.Connection, component_id: str) -> dict[str, Any]:
    if component_id in FAILING_COMPONENT_IDS:
        raise AdapterError(
            f"parts catalog lookup failed for '{component_id}' (simulated outage)"
        )
    row = conn.execute(
        "SELECT * FROM parts_catalog WHERE component_id = ?", (component_id,)
    ).fetchone()
    if row is None:
        return {
            "_source": SYNTHETIC_NOTICE,
            "component_id": component_id,
            "replacement_cost_usd": None,
            "stock_status": "not_cataloged",
        }
    return {
        "_source": SYNTHETIC_NOTICE,
        "component_id": component_id,
        "replacement_cost_usd": row["replacement_cost_usd"],
        "stock_status": row["stock_status"],
    }
