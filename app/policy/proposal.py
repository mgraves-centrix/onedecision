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
from app.policy.schema import POLICY_FAMILY, PolicyDefinition, spec_for


def proposal_to_payload(proposal: PolicyProposal, family: str = POLICY_FAMILY) -> dict[str, Any]:
    """Assemble the policy payload. Still untrusted; still validated downstream.

    The agent proposes conditions and a cap; the domain supplies the action set,
    so there is nowhere for a model to write an action of its own.
    """
    actions = spec_for(family).fixed_actions(float(proposal.max_cost_usd))

    return {
        "family": family,
        "name": proposal.name,
        "description": proposal.description,
        "conditions": [
            {"field": c.field, "operator": c.operator, "value": c.value}
            for c in proposal.conditions
        ],
        "actions": actions,
        "min_confidence": proposal.min_confidence,
    }


# ------------------------------------------------------------------ revision

REVISABLE_FIELDS = ("replacement_cost_usd", "min_confidence", "kit_category")


class RevisionError(ValueError):
    """A revision that the schema or the revision rules will not accept."""


def revised_payload(
    definition: PolicyDefinition,
    *,
    max_cost_usd: float,
    min_confidence: float,
    kit_category: str | None = None,
) -> dict[str, Any]:
    """Apply a human revision to a candidate.

    A revision is deliberately narrow in what it can touch:

    * the **spend cap** and its matching cost condition,
    * the **minimum confidence** the agent must have, and
    * an optional **kit-category restriction**, which only ever removes cases.

    It cannot remove a condition, add an action, or reach any field outside the
    allowlist — those are not restrictions enforced by a check further down, they
    are simply things this function has no way to express. A human can therefore
    tighten what the agent proposed, or loosen it within the hard guardrails, but
    cannot strip a safety condition out of a policy by editing it.

    The result is still an untrusted payload: it goes through the same schema
    validation and the same replay gate as anything the model proposes.
    """
    cap = min(float(max_cost_usd), MAX_REPLACEMENT_COST_CEILING_USD)
    if cap <= 0:
        raise RevisionError("spend cap must be greater than zero")
    spec = spec_for(definition.family)

    conditions: list[dict[str, Any]] = []
    saw_cost = False
    for condition in definition.conditions:
        if condition.field == "kit_category":
            continue  # replaced below, if the revision asks for one
        if condition.field == "replacement_cost_usd" and condition.operator in {"lte", "lt"}:
            conditions.append({"field": condition.field, "operator": condition.operator, "value": cap})
            saw_cost = True
            continue
        conditions.append(
            {"field": condition.field, "operator": condition.operator, "value": condition.value}
        )
    if not saw_cost:
        conditions.append({"field": "replacement_cost_usd", "operator": "lte", "value": cap})

    if kit_category:
        conditions.append({"field": "kit_category", "operator": "eq", "value": kit_category})

    return {
        "family": definition.family,
        "name": definition.name,
        # The proposal's prose described the numbers the agent chose. Carrying it
        # over unchanged would leave the policy describing a cap it no longer has,
        # so the revised terms are restated here.
        "description": _revised_description(definition, cap, float(min_confidence), kit_category),
        "conditions": conditions,
        "actions": spec.fixed_actions(cap),
        "min_confidence": float(min_confidence),
    }


def _revised_description(
    definition: PolicyDefinition, cap: float, min_confidence: float, kit_category: str | None
) -> str:
    """Describe a revision without restating its conditions in prose.

    The agent's proposal described its own numbers in a sentence. Keeping that
    sentence and appending the revised terms produces a policy that claims two
    different spend caps — which is worse than either alone. The conditions are
    already listed in full, authoritatively, wherever a policy is shown, so the
    description says what a person changed and nothing that can contradict it.
    """
    scope = f", limited to {kit_category.replace('_', ' ')}s" if kit_category else ""
    return (
        f"Revised by a person from the agent's proposal: at most ${cap:.2f} per "
        f"replacement, agent confidence at least {min_confidence:.2f}{scope}. "
        "Every other condition is unchanged from the proposal and is listed in full below."
    )[:600]
