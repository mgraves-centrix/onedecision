"""Turn an agent proposal into a candidate policy payload.

The agent proposes *conditions* and a *spend cap*. It does not propose actions:
the action set is assembled here from the allowlist. That is deliberate — there
is no field anywhere in `PolicyProposal` into which a model could write a novel
action, so "the model invented a new action" is not a failure mode that needs
detecting.
"""

from __future__ import annotations

from typing import Any

from app.config import MAX_REPLACEMENT_COST_CEILING_USD
from app.domain import PolicyProposal
from app.policy.schema import POLICY_FAMILY

FIXED_ACTIONS: list[dict[str, Any]] = [
    {"type": "set_disposition", "disposition": "PARTS_HOLD"},
    {"type": "create_work_order", "work_order_type": "REPLACEMENT_PARTS", "max_cost_usd": None},
    {"type": "close_exception", "resolution_code": "RESOLVED_PARTS_REPLACEMENT"},
]


def proposal_to_payload(proposal: PolicyProposal) -> dict[str, Any]:
    """Assemble the policy payload. Still untrusted; still validated downstream."""
    cap = min(float(proposal.max_cost_usd), MAX_REPLACEMENT_COST_CEILING_USD)

    actions: list[dict[str, Any]] = []
    for template in FIXED_ACTIONS:
        action = dict(template)
        if action["type"] == "create_work_order":
            action["max_cost_usd"] = cap
        actions.append(action)

    return {
        "family": POLICY_FAMILY,
        "name": proposal.name,
        "description": proposal.description,
        "conditions": [
            {"field": c.field, "operator": c.operator, "value": c.value}
            for c in proposal.conditions
        ],
        "actions": actions,
        "min_confidence": proposal.min_confidence,
    }
