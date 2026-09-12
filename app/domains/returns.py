"""Domain pack: returns, a kit back from a rental missing an accessory.

This is the domain the product was built around. Everything here was previously
hard-coded into the policy language, the replay gate, and the orchestrator; it is
gathered in one place so a second domain can exist beside it without touching any
of that machinery.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.db import Connection

from app.adapters import warehouse
from app.adapters.returns_system import AdapterError
from app.config import MAX_MISSING_COMPONENTS_CEILING, MAX_REPLACEMENT_COST_CEILING_USD
from app.domains import ActionSpec, DomainSpec, register
from app.facts import derive_facts
from app.policy.guardrails import evaluate_guardrails

FAMILY = "returns.missing_accessory"

BOOL_FIELDS = frozenset(
    {
        "missing_component_serialized",
        "missing_component_safety_critical",
        "missing_component_essential",
        "serial_match",
        "new_damage_present",
        "evidence_complete",
    }
)

NUMBER_FIELDS = frozenset({"missing_component_count", "replacement_cost_usd"})

ENUM_FIELDS = {"kit_category": frozenset({"camera_kit", "lens_kit", "audio_kit", "drone_kit"})}

# Outer walls. A proposal may be tighter than these. It may never be looser.
NUMERIC_CEILINGS = {
    "replacement_cost_usd": MAX_REPLACEMENT_COST_CEILING_USD,
    "missing_component_count": float(MAX_MISSING_COMPONENTS_CEILING),
}

ACTIONS = (
    ActionSpec(type="set_disposition", literals={"disposition": ("PARTS_HOLD",)}),
    ActionSpec(
        type="create_work_order",
        literals={"work_order_type": ("REPLACEMENT_PARTS",)},
        caps={"max_cost_usd": MAX_REPLACEMENT_COST_CEILING_USD},
        bound_by=("max_cost_usd", "replacement_cost_usd"),
    ),
    ActionSpec(type="close_exception", literals={"resolution_code": ("RESOLVED_PARTS_REPLACEMENT",)}),
)


def fixed_actions(cap: float) -> list[dict[str, Any]]:
    """The action set a proposal always gets. The agent never chooses these."""
    return [
        {"type": "set_disposition", "disposition": "PARTS_HOLD"},
        {
            "type": "create_work_order",
            "work_order_type": "REPLACEMENT_PARTS",
            "max_cost_usd": min(float(cap), MAX_REPLACEMENT_COST_CEILING_USD),
        },
        {"type": "close_exception", "resolution_code": "RESOLVED_PARTS_REPLACEMENT"},
    ]


def corpus(conn: "Connection") -> list[tuple[str, str, str]]:
    rows = conn.execute(
        """SELECT case_id, expected_label, scenario_note FROM return_cases
            WHERE is_historical = ? ORDER BY case_id""",
        (True,),
    ).fetchall()
    return [(r["case_id"], r["expected_label"], r["scenario_note"] or "") for r in rows]


def execute(conn: "Connection", action: Any, *, facts: Any, idem_key: str) -> dict[str, Any]:
    """Perform one business-system write. Raises AdapterError if it cannot.

    The orchestrator owns the loop, the audit records, and closing the exception;
    a domain owns only its own systems.
    """
    component = facts.missing_components[0] if facts.missing_components else None

    if action.type == "set_disposition":
        out = warehouse.set_disposition(
            conn, case_id=facts.case_id, disposition=action.disposition, idempotency_key=idem_key
        )
        return {
            "label": f"set_disposition:{action.disposition}",
            "detail": f"disposition set to {action.disposition}",
            "duplicate_suppressed": out["duplicate_suppressed"],
            "reference": facts.case_id,
        }

    if action.type == "create_work_order":
        if component is None:
            raise AdapterError("no missing component to raise a work order for")
        if facts.replacement_cost_usd is None:
            raise AdapterError("replacement cost unavailable at execution time")
        out = warehouse.create_work_order(
            conn,
            case_id=facts.case_id,
            work_order_type=action.work_order_type,
            component_id=component.component_id,
            cost_usd=facts.replacement_cost_usd,
            max_cost_usd=action.max_cost_usd,
            idempotency_key=idem_key,
        )
        return {
            "label": f"create_work_order:{action.work_order_type}",
            "detail": (
                f"{out['work_order_id']} for {component.component_id} at "
                f"${facts.replacement_cost_usd:.2f}"
            ),
            "duplicate_suppressed": out["duplicate_suppressed"],
            "reference": out["work_order_id"],
        }

    raise AdapterError(f"'{action.type}' is not an action this domain performs")


def verify(conn: "Connection", case_id: str) -> tuple[list[str], list[str]]:
    """Read the business systems back. Returns (checks passed, failures)."""
    checks: list[str] = []
    failures: list[str] = []

    disposition = warehouse.get_disposition(conn, case_id)
    if disposition and disposition["disposition"] == "PARTS_HOLD":
        checks.append(f"disposition is {disposition['disposition']}")
    else:
        failures.append("disposition was not written as PARTS_HOLD")

    work_orders = warehouse.get_work_orders(conn, case_id)
    if len(work_orders) == 1:
        checks.append(f"one work order on file: {work_orders[0]['work_order_id']}")
    elif not work_orders:
        failures.append("no replacement-parts work order was created")
    else:
        failures.append(f"{len(work_orders)} work orders exist for this case; expected exactly one")

    return checks, failures


SPEC = register(
    DomainSpec(
        family=FAMILY,
        label="Returns — missing accessory",
        subject="return case",
        bool_fields=BOOL_FIELDS,
        number_fields=NUMBER_FIELDS,
        enum_fields=ENUM_FIELDS,
        numeric_ceilings=NUMERIC_CEILINGS,
        actions=ACTIONS,
        required_action_types=("set_disposition", "create_work_order", "close_exception"),
        derive_facts=derive_facts,
        guardrails=evaluate_guardrails,
        corpus=corpus,
        execute=execute,
        verify=verify,
        fixed_actions=fixed_actions,
    )
)
