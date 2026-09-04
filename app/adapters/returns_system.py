"""SYNTHETIC ADAPTER — returns management system (read-only)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db import Connection

import json
from typing import Any

from app.adapters import SYNTHETIC_NOTICE


class AdapterError(RuntimeError):
    """A synthetic-system failure. Always escalates; never silently ignored."""


REQUIRED_EVIDENCE_FIELDS = (
    "exterior_photo",
    "serial_photo",
    "component_checklist",
    "inspector_id",
    "weight_check",
)


def get_return_case(conn: "Connection", case_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM return_cases WHERE case_id = ?", (case_id,)).fetchone()
    if row is None:
        raise AdapterError(f"return case '{case_id}' not found in the returns system")
    kit = conn.execute("SELECT * FROM kit_catalog WHERE sku = ?", (row["sku"],)).fetchone()
    if kit is None:
        raise AdapterError(f"kit '{row['sku']}' not found in the catalog")
    return {
        "_source": SYNTHETIC_NOTICE,
        "case_id": row["case_id"],
        "order_id": row["order_id"],
        "customer_ref": row["customer_ref"],
        "sku": row["sku"],
        "kit_name": kit["name"],
        "kit_category": kit["category"],
        "declared_value_usd": float(kit["declared_value_usd"]),
        "expected_serial": row["expected_serial"],
        "received_serial": row["received_serial"],
        "received_components": json.loads(row["received_components"]),
        "inspection_evidence": json.loads(row["inspection_evidence"]),
        "new_damage_present": bool(row["new_damage_present"]),
        "inspector_notes": row["inspector_notes"],
        "received_at": row["received_at"],
    }


def get_expected_components(conn: "Connection", sku: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM kit_components WHERE sku = ? ORDER BY component_id", (sku,)
    ).fetchall()
    if not rows:
        raise AdapterError(f"no bill of materials on file for kit '{sku}'")
    return [
        {
            "component_id": r["component_id"],
            "name": r["name"],
            "serialized": bool(r["serialized"]),
            "safety_critical": bool(r["safety_critical"]),
            "essential": bool(r["essential"]),
        }
        for r in rows
    ]


def missing_evidence_fields(evidence: dict[str, Any]) -> list[str]:
    missing = []
    for field in REQUIRED_EVIDENCE_FIELDS:
        value = evidence.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing
