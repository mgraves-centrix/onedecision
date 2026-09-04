"""Seed and reset the demo from the synthetic fixtures.

`python -m app.seed --reset` drops local state and rebuilds it, so the demo is
always reproducible from a clean base. Fixtures live in `fixtures/` and are
entirely invented; see docs/scope.md.
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from app import audit, db
from app.audit import AuditEventType
from app.config import REPO_ROOT

FIXTURES = REPO_ROOT / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def seed(reset: bool = False, path: Path | None = None) -> dict[str, int]:
    if reset:
        db.drop_all(path)
    db.init_db(path)

    catalogue = _load("catalogue.json")
    cases = _load("cases.json")
    counts = {"kits": 0, "components": 0, "parts": 0, "historical_cases": 0, "demo_cases": 0}

    with db.session(path) as conn:
        conn.execute("DELETE FROM kit_components")
        conn.execute("DELETE FROM parts_catalogue")
        conn.execute("DELETE FROM work_orders")
        conn.execute("DELETE FROM dispositions")
        conn.execute("DELETE FROM decision_cards")
        conn.execute("DELETE FROM exceptions")
        conn.execute("DELETE FROM policies")
        conn.execute("DELETE FROM return_cases")
        conn.execute("DELETE FROM kit_catalogue")

        for kit in catalogue["kits"]:
            conn.execute(
                "INSERT INTO kit_catalogue (sku, name, category, declared_value_usd) VALUES (?,?,?,?)",
                (kit["sku"], kit["name"], kit["category"], kit["declared_value_usd"]),
            )
            counts["kits"] += 1

        for comp in catalogue["components"]:
            conn.execute(
                """INSERT INTO kit_components (sku, component_id, name, serialized,
                       safety_critical, essential) VALUES (?,?,?,?,?,?)""",
                (
                    comp["sku"],
                    comp["component_id"],
                    comp["name"],
                    comp["serialized"],
                    comp["safety_critical"],
                    comp["essential"],
                ),
            )
            counts["components"] += 1

        for part in catalogue["parts"]:
            conn.execute(
                "INSERT INTO parts_catalogue (component_id, replacement_cost_usd, stock_status) VALUES (?,?,?)",
                (part["component_id"], part["replacement_cost_usd"], part["stock_status"]),
            )
            counts["parts"] += 1

        for bucket, key in (("historical_cases", "historical_cases"), ("demo_cases", "demo_cases")):
            for case in cases[key]:
                conn.execute(
                    """INSERT INTO return_cases (case_id, order_id, customer_ref, sku,
                           expected_serial, received_serial, received_components,
                           inspection_evidence, new_damage_present, inspector_notes,
                           received_at, expected_label, scenario_note, is_historical)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        case["case_id"],
                        case["order_id"],
                        case["customer_ref"],
                        case["sku"],
                        case["expected_serial"],
                        case["received_serial"],
                        json.dumps(case["received_components"]),
                        json.dumps(case["inspection_evidence"]),
                        case["new_damage_present"],
                        case["inspector_notes"],
                        case["received_at"],
                        case["expected_label"],
                        case["scenario_note"],
                        case["is_historical"],
                    ),
                )
                counts[bucket] += 1

        audit.record(
            conn,
            trace_id=f"trc_{uuid.uuid4().hex[:12]}",
            event_type=AuditEventType.DEMO_RESET,
            actor="operator",
            payload={"counts": counts, "source": "fixtures/", "synthetic": True},
        )

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the OneDecision demo database.")
    parser.add_argument("--reset", action="store_true", help="drop local state before seeding")
    args = parser.parse_args()
    counts = seed(reset=args.reset)
    print("Seeded synthetic fixtures:")
    for key, value in counts.items():
        print(f"  {key:>18}: {value}")
    print(f"\nDatabase: {db.db_path()}")


if __name__ == "__main__":
    main()
