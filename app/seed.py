"""Seed and reset the demo from the synthetic fixtures.

`python -m app.seed --reset` drops local state and rebuilds it, so the demo is
always reproducible from a clean base. Fixtures live in `fixtures/` and are
entirely invented; see docs/scope.md.
"""

from __future__ import annotations

import argparse
import json
import uuid
from app import audit, db
from app.audit import AuditEventType
from app.config import REPO_ROOT

FIXTURES = REPO_ROOT / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def seed(reset: bool = False) -> dict[str, int]:
    if reset:
        db.drop_all()
    db.init_db()

    catalog = _load("catalog.json")
    cases = _load("cases.json")
    invoices = _load("ap_invoices.json")
    counts = {
        "kits": 0,
        "components": 0,
        "parts": 0,
        "historical_cases": 0,
        "demo_cases": 0,
        "vendors": 0,
        "historical_invoices": 0,
        "demo_invoices": 0,
    }

    with db.session() as conn:
        conn.execute("DELETE FROM kit_components")
        conn.execute("DELETE FROM parts_catalog")
        conn.execute("DELETE FROM work_orders")
        conn.execute("DELETE FROM dispositions")
        conn.execute("DELETE FROM decision_cards")
        conn.execute("DELETE FROM exceptions")
        conn.execute("DELETE FROM policies")
        conn.execute("DELETE FROM return_cases")
        conn.execute("DELETE FROM kit_catalog")
        conn.execute("DELETE FROM ap_adjustments")
        conn.execute("DELETE FROM ap_payment_releases")
        conn.execute("DELETE FROM ap_invoices")
        conn.execute("DELETE FROM ap_vendors")

        for kit in catalog["kits"]:
            conn.execute(
                "INSERT INTO kit_catalog (sku, name, category, declared_value_usd) VALUES (?,?,?,?)",
                (kit["sku"], kit["name"], kit["category"], kit["declared_value_usd"]),
            )
            counts["kits"] += 1

        for comp in catalog["components"]:
            conn.execute(
                """INSERT INTO kit_components (sku, component_id, name, serialized,
                       safety_critical, essential) VALUES (?,?,?,?,?,?)""",
                (
                    comp["sku"],
                    comp["component_id"],
                    comp["name"],
                    bool(comp["serialized"]),
                    bool(comp["safety_critical"]),
                    bool(comp["essential"]),
                ),
            )
            counts["components"] += 1

        for part in catalog["parts"]:
            conn.execute(
                "INSERT INTO parts_catalog (component_id, replacement_cost_usd, stock_status) VALUES (?,?,?)",
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
                        bool(case["new_damage_present"]),
                        case["inspector_notes"],
                        case["received_at"],
                        case["expected_label"],
                        case["scenario_note"],
                        bool(case["is_historical"]),
                    ),
                )
                counts[bucket] += 1

        for vendor in invoices["vendors"]:
            conn.execute(
                "INSERT INTO ap_vendors (vendor_id, name, risk_tier, on_hold) VALUES (?,?,?,?)",
                (vendor["vendor_id"], vendor["name"], vendor["risk_tier"], bool(vendor["on_hold"])),
            )
            counts["vendors"] += 1

        for bucket, key in (
            ("historical_invoices", "historical_invoices"),
            ("demo_invoices", "demo_invoices"),
        ):
            for invoice in invoices[key]:
                conn.execute(
                    """INSERT INTO ap_invoices (invoice_id, vendor_id, vendor_invoice_no,
                           po_number, po_total_usd, received_total_usd, invoice_total_usd,
                           tax_amount_usd, expected_tax_usd, currency, evidence,
                           submitter_notes, received_at, expected_label, scenario_note,
                           is_historical)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        invoice["invoice_id"],
                        invoice["vendor_id"],
                        invoice["vendor_invoice_no"],
                        invoice["po_number"],
                        invoice["po_total_usd"],
                        invoice["received_total_usd"],
                        invoice["invoice_total_usd"],
                        invoice["tax_amount_usd"],
                        invoice["expected_tax_usd"],
                        invoice["currency"],
                        json.dumps(invoice["evidence"]),
                        invoice["submitter_notes"],
                        invoice["received_at"],
                        invoice["expected_label"],
                        invoice["scenario_note"],
                        bool(invoice["is_historical"]),
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
    print(f"\nDatabase: {db.describe()}")


if __name__ == "__main__":
    main()
