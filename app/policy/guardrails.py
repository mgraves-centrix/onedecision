"""Non-overridable invariants.

These run **before** any policy is consulted and cannot be relaxed by a policy,
a human approval, or a model. A policy can only ever narrow what automation is
permitted; the guardrails set the outer wall.

If any invariant fails, the case escalates. Full stop.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import (
    MAX_MISSING_COMPONENTS_CEILING,
    MAX_REPLACEMENT_COST_CEILING_USD,
    settings,
)
from app.domain import CaseFacts


@dataclass(frozen=True)
class GuardrailResult:
    passed: bool
    reasons: tuple[str, ...]

    @property
    def blocked(self) -> bool:
        return not self.passed


def evaluate_guardrails(
    facts: CaseFacts,
    *,
    confidence: float | None = None,
    tool_failures: tuple[str, ...] = (),
    matching_policy_count: int = 0,
) -> GuardrailResult:
    """Evaluate the hard invariants for automatic action on this case."""
    reasons: list[str] = []

    failures = tuple(tool_failures) or facts.tool_failures
    if failures:
        reasons.append(f"tool failure during investigation: {', '.join(failures)}")

    if not facts.evidence_complete:
        missing = ", ".join(facts.missing_evidence_fields) or "unspecified fields"
        reasons.append(f"inspection evidence is incomplete ({missing})")

    if not facts.serial_match:
        reasons.append("serial number does not match the expected serial")

    if facts.new_damage_present:
        reasons.append("new damage is present on the returned item")

    if facts.missing_component_count == 0:
        reasons.append("no missing component identified; nothing for a policy to act on")
    elif facts.missing_component_count > MAX_MISSING_COMPONENTS_CEILING:
        reasons.append(
            f"{facts.missing_component_count} components missing; the hard ceiling is "
            f"{MAX_MISSING_COMPONENTS_CEILING}"
        )

    if facts.missing_component_serialized:
        reasons.append("missing component is serialized")
    if facts.missing_component_safety_critical:
        reasons.append("missing component is safety-critical")
    if facts.missing_component_essential:
        reasons.append("missing component is essential to the kit")

    if facts.replacement_cost_usd is None:
        reasons.append("replacement cost is unavailable")
    elif facts.replacement_cost_usd > MAX_REPLACEMENT_COST_CEILING_USD:
        reasons.append(
            f"replacement cost ${facts.replacement_cost_usd:.2f} exceeds the hard ceiling "
            f"${MAX_REPLACEMENT_COST_CEILING_USD:.2f}"
        )

    if confidence is not None and confidence < settings.confidence_threshold:
        reasons.append(
            f"agent confidence {confidence:.2f} is below the threshold "
            f"{settings.confidence_threshold:.2f}"
        )

    if matching_policy_count > 1:
        reasons.append(
            f"{matching_policy_count} active policies match this case; policies conflict"
        )

    return GuardrailResult(passed=not reasons, reasons=tuple(reasons))
