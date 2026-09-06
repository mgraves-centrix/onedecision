"""Structural diff between two policy versions.

The diff is not decoration. A supervisor activating version 2 needs to see, in
one glance, what changes about the boundary they already approved — and in
particular whether anything got **wider**. Every row is classified, and widening
is called out rather than left for the reader to work out from two numbers.

Direction is defined against the set of cases a policy would act on:

* **narrower** — the policy now acts on strictly fewer cases (a lower spend cap,
  a higher confidence floor, an added condition).
* **wider** — it acts on more (a raised cap, a lowered floor, a removed
  condition). Still inside the hard guardrails, which no policy can cross.
* **changed** — neither, for values that are not ordered (a boolean flipped, a
  category swapped).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.policy.schema import Condition, Operator, PolicyDefinition

# Operators where a larger literal admits more cases.
_UPPER_BOUND = {Operator.LT, Operator.LTE}
# Operators where a larger literal admits fewer cases.
_LOWER_BOUND = {Operator.GT, Operator.GTE}


class ChangeKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    NARROWED = "narrowed"
    WIDENED = "widened"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


WIDENING_KINDS = frozenset({ChangeKind.REMOVED, ChangeKind.WIDENED})


@dataclass(frozen=True)
class DiffRow:
    label: str
    before: str | None
    after: str | None
    kind: ChangeKind
    note: str = ""

    @property
    def widens(self) -> bool:
        return self.kind in WIDENING_KINDS


@dataclass
class PolicyDiff:
    baseline_label: str
    candidate_label: str
    rows: list[DiffRow] = field(default_factory=list)

    @property
    def changed_rows(self) -> list[DiffRow]:
        return [r for r in self.rows if r.kind is not ChangeKind.UNCHANGED]

    @property
    def has_changes(self) -> bool:
        return bool(self.changed_rows)

    @property
    def widening_rows(self) -> list[DiffRow]:
        return [r for r in self.rows if r.widens]

    @property
    def widens(self) -> bool:
        return bool(self.widening_rows)

    @property
    def summary(self) -> str:
        if not self.has_changes:
            return "identical to the baseline"
        parts = []
        for kind in (ChangeKind.ADDED, ChangeKind.REMOVED, ChangeKind.NARROWED,
                     ChangeKind.WIDENED, ChangeKind.CHANGED):
            n = sum(1 for r in self.rows if r.kind is kind)
            if n:
                parts.append(f"{n} {kind.value}")
        return ", ".join(parts)


def _numeric_direction(operator: Operator, before: float, after: float) -> ChangeKind:
    if after == before:
        return ChangeKind.UNCHANGED
    if operator in _UPPER_BOUND:
        return ChangeKind.WIDENED if after > before else ChangeKind.NARROWED
    if operator in _LOWER_BOUND:
        return ChangeKind.NARROWED if after > before else ChangeKind.WIDENED
    return ChangeKind.CHANGED


def _condition_row(field_name: str, before: Condition | None, after: Condition | None) -> DiffRow:
    if before is None and after is not None:
        return DiffRow(
            label=field_name,
            before=None,
            after=after.describe(),
            kind=ChangeKind.ADDED,
            note="a new condition the policy must satisfy",
        )
    if after is None and before is not None:
        return DiffRow(
            label=field_name,
            before=before.describe(),
            after=None,
            kind=ChangeKind.REMOVED,
            note="this condition no longer has to hold",
        )

    assert before is not None and after is not None
    if before.operator == after.operator and before.value == after.value:
        return DiffRow(field_name, before.describe(), after.describe(), ChangeKind.UNCHANGED)

    kind = ChangeKind.CHANGED
    if before.operator == after.operator and not isinstance(before.value, (bool, str, list)):
        if not isinstance(after.value, (bool, str, list)):
            kind = _numeric_direction(before.operator, float(before.value), float(after.value))
    return DiffRow(field_name, before.describe(), after.describe(), kind)


def diff_policies(
    baseline: PolicyDefinition | None,
    candidate: PolicyDefinition,
    *,
    baseline_label: str = "active version",
    candidate_label: str = "candidate",
) -> PolicyDiff:
    """Diff a candidate against a baseline. A null baseline means nothing is live yet."""
    out = PolicyDiff(baseline_label=baseline_label, candidate_label=candidate_label)

    if baseline is None:
        for condition in candidate.conditions:
            out.rows.append(
                DiffRow(
                    label=condition.field,
                    before=None,
                    after=condition.describe(),
                    kind=ChangeKind.ADDED,
                    note="no approved policy exists yet, so every condition is new",
                )
            )
        out.rows.append(
            DiffRow("spend cap", None, f"${_spend_cap(candidate):.2f}", ChangeKind.ADDED)
        )
        out.rows.append(
            DiffRow("minimum confidence", None, f"{candidate.min_confidence:.2f}", ChangeKind.ADDED)
        )
        return out

    before_by_field = {c.field: c for c in baseline.conditions}
    after_by_field = {c.field: c for c in candidate.conditions}
    for name in sorted(set(before_by_field) | set(after_by_field)):
        out.rows.append(_condition_row(name, before_by_field.get(name), after_by_field.get(name)))

    before_cap, after_cap = _spend_cap(baseline), _spend_cap(candidate)
    out.rows.append(
        DiffRow(
            "spend cap",
            f"${before_cap:.2f}",
            f"${after_cap:.2f}",
            _numeric_direction(Operator.LTE, before_cap, after_cap),
            note="the most this policy may authorize on one work order",
        )
    )

    out.rows.append(
        DiffRow(
            "minimum confidence",
            f"{baseline.min_confidence:.2f}",
            f"{candidate.min_confidence:.2f}",
            # A higher floor admits fewer cases, so it behaves like a lower bound.
            _numeric_direction(Operator.GTE, baseline.min_confidence, candidate.min_confidence),
            note="how sure the agent must be before this policy may act",
        )
    )
    return out


def _spend_cap(definition: PolicyDefinition) -> float:
    for action in definition.actions:
        if action.type == "create_work_order":
            return float(action.max_cost_usd)
    return 0.0
