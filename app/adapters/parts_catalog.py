"""SYNTHETIC ADAPTER — replacement parts catalog (read-only)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db import Connection

from typing import Any

from app.adapters import SYNTHETIC_NOTICE
from app.adapters.returns_system import AdapterError

# Component ids that deliberately make the synthetic catalog fail, so the
# tool-failure escalation path is exercised rather than assumed.
FAILING_COMPONENT_IDS = frozenset({"CMP-FAULT-SIM"})


def lookup_replacement_cost(conn: "Connection", component_id: str) -> dict[str, Any]:
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
    cost = row["replacement_cost_usd"]
    return {
        "_source": SYNTHETIC_NOTICE,
        "component_id": component_id,
        # PostgreSQL stores money as NUMERIC and hands back Decimal. Coerce here
        # so no Decimal escapes the adapter into the domain or the policy engine.
        "replacement_cost_usd": None if cost is None else float(cost),
        "stock_status": row["stock_status"],
    }
