"""Deterministic fact derivation.

`CaseFacts` come from here and only from here. The agent's report is compared
against these facts; it never replaces them. This is what stops a hallucination
— or a prompt injection buried in an inspector's note — from driving an action.
"""

from __future__ import annotations

import sqlite3

from app.adapters import parts_catalog, returns_system
from app.adapters.returns_system import AdapterError
from app.domain import CaseFacts, InvestigationReport, MissingComponent


def derive_facts(conn: sqlite3.Connection, case_id: str) -> CaseFacts:
    """Build the normalized, policy-testable view of a case."""
    tool_failures: list[str] = []

    case = returns_system.get_return_case(conn, case_id)
    expected = returns_system.get_expected_components(conn, case["sku"])

    received_ids = set(case["received_components"])
    expected_by_id = {c["component_id"]: c for c in expected}
    missing_ids = sorted(set(expected_by_id) - received_ids)
    unexpected = tuple(sorted(received_ids - set(expected_by_id)))

    missing: list[MissingComponent] = []
    total_cost: float | None = 0.0
    for component_id in missing_ids:
        spec = expected_by_id[component_id]
        cost: float | None = None
        stock = "unknown"
        try:
            priced = parts_catalog.lookup_replacement_cost(conn, component_id)
            cost = priced["replacement_cost_usd"]
            stock = priced["stock_status"]
        except AdapterError as exc:
            tool_failures.append(str(exc))
        missing.append(
            MissingComponent(
                component_id=component_id,
                name=spec["name"],
                serialized=spec["serialized"],
                safety_critical=spec["safety_critical"],
                essential=spec["essential"],
                replacement_cost_usd=cost,
                stock_status=stock,
            )
        )
        if cost is None:
            total_cost = None
        elif total_cost is not None:
            total_cost += cost

    if not missing:
        total_cost = None

    evidence_gaps = returns_system.missing_evidence_fields(case["inspection_evidence"])
    received_serial = case["received_serial"]
    serial_match = bool(received_serial) and received_serial == case["expected_serial"]

    return CaseFacts(
        case_id=case["case_id"],
        sku=case["sku"],
        kit_category=case["kit_category"],
        missing_component_count=len(missing),
        missing_component_serialized=any(c.serialized for c in missing),
        missing_component_safety_critical=any(c.safety_critical for c in missing),
        missing_component_essential=any(c.essential for c in missing),
        serial_match=serial_match,
        replacement_cost_usd=total_cost,
        new_damage_present=case["new_damage_present"],
        evidence_complete=not evidence_gaps,
        missing_components=tuple(missing),
        unexpected_components=unexpected,
        missing_evidence_fields=tuple(evidence_gaps),
        expected_serial=case["expected_serial"],
        received_serial=received_serial,
        tool_failures=tuple(tool_failures),
    )


RECONCILED_FIELDS = (
    ("observed_missing_component_count", "missing_component_count"),
    ("observed_serial_match", "serial_match"),
    ("observed_new_damage", "new_damage_present"),
    ("observed_evidence_complete", "evidence_complete"),
    ("observed_replacement_cost_usd", "replacement_cost_usd"),
)


def reconcile(report: InvestigationReport, facts: CaseFacts) -> list[str]:
    """Compare the agent's claims to the deterministic truth.

    Any disagreement is returned as a discrepancy string. Discrepancies block
    automatic action — the ground truth wins and the case escalates, so a wrong
    or manipulated model report can only ever be *more* conservative.
    """
    discrepancies: list[str] = []
    for report_field, fact_field in RECONCILED_FIELDS:
        claimed = getattr(report, report_field)
        actual = getattr(facts, fact_field)
        if isinstance(actual, float) or isinstance(claimed, float):
            if claimed is None or actual is None:
                if claimed != actual:
                    discrepancies.append(
                        f"agent reported {report_field}={claimed}, system holds {fact_field}={actual}"
                    )
                continue
            if abs(float(claimed) - float(actual)) > 0.005:
                discrepancies.append(
                    f"agent reported {report_field}={claimed}, system holds {fact_field}={actual}"
                )
            continue
        if claimed != actual:
            discrepancies.append(
                f"agent reported {report_field}={claimed}, system holds {fact_field}={actual}"
            )
    if report.case_id != facts.case_id:
        discrepancies.append(
            f"agent reported case_id={report.case_id}, investigation was for {facts.case_id}"
        )
    return discrepancies
