"""Deterministic policy evaluation.

Reads a `PolicyDefinition` (data) and a `CaseFacts.policy_view()` (data) and
returns a boolean. No dynamic execution of any kind.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain import CaseFacts
from app.policy.schema import Condition, Operator, PolicyDefinition


@dataclass
class ConditionOutcome:
    condition: str
    observed: object
    passed: bool


@dataclass
class MatchResult:
    matched: bool
    outcomes: list[ConditionOutcome] = field(default_factory=list)
    unmet: list[str] = field(default_factory=list)


def _compare(operator: Operator, observed: object, expected: object) -> bool:
    if observed is None:
        # A missing fact never satisfies a condition. Default to "no match".
        return False
    match operator:
        case Operator.EQ:
            return observed == expected
        case Operator.NEQ:
            return observed != expected
        case Operator.IN:
            return isinstance(expected, list) and observed in expected
        case Operator.NOT_IN:
            return isinstance(expected, list) and observed not in expected
        case Operator.LT | Operator.LTE | Operator.GT | Operator.GTE:
            if isinstance(observed, bool) or not isinstance(observed, (int, float)):
                return False
            if not isinstance(expected, (int, float)):
                return False
            match operator:
                case Operator.LT:
                    return observed < expected
                case Operator.LTE:
                    return observed <= expected
                case Operator.GT:
                    return observed > expected
                case _:
                    return observed >= expected
    return False


def evaluate_condition(condition: Condition, view: dict[str, object]) -> ConditionOutcome:
    observed = view.get(condition.field)
    passed = _compare(condition.operator, observed, condition.value)
    return ConditionOutcome(condition=condition.describe(), observed=observed, passed=passed)


def match_policy(policy: PolicyDefinition, facts: CaseFacts) -> MatchResult:
    """True only if every condition holds. All conditions are ANDed."""
    view = facts.policy_view()
    outcomes = [evaluate_condition(c, view) for c in policy.conditions]
    unmet = [o.condition for o in outcomes if not o.passed]
    return MatchResult(matched=not unmet, outcomes=outcomes, unmet=unmet)


def select_matching_policies(
    policies: list[tuple[str, PolicyDefinition]], facts: CaseFacts
) -> list[tuple[str, PolicyDefinition, MatchResult]]:
    """Return every active policy whose conditions hold. More than one is a conflict."""
    hits = []
    for policy_id, definition in policies:
        result = match_policy(definition, facts)
        if result.matched:
            hits.append((policy_id, definition, result))
    return hits
