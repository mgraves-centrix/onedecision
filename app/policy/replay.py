"""Replay a candidate policy against labeled historical cases.

Replay is a **dry run**: it derives facts, evaluates the guardrails and the
candidate policy, and compares the predicted outcome against the recorded
ground-truth label. It never writes to a business system.

Activation is blocked unless replay passes. The bar is deliberately blunt:
zero false automatic actions, and the policy must actually automate something.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db import Connection

from dataclasses import asdict, dataclass, field
from typing import Any

from app.policy.engine import match_policy
from app.policy.schema import PolicyDefinition, spec_for

# Ground-truth labels carried by the synthetic historical cases.
LABEL_AUTO = "auto_resolve"
LABEL_ESCALATE = "escalate"

MIN_AUTOMATION_COVERAGE = 0.60


@dataclass
class ReplayCaseResult:
    case_id: str
    expected: str
    predicted: str
    correct: bool
    reasons: list[str] = field(default_factory=list)
    scenario_note: str = ""


@dataclass
class ReplayReport:
    policy_name: str
    cases_replayed: int
    correct_auto_resolutions: int
    correct_escalations: int
    false_automatic_actions: int
    missed_automations: int
    automation_coverage: float
    coverage_floor_enforced: bool
    passed: bool
    blocking_reasons: list[str] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    results: list[ReplayCaseResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["results"] = [asdict(r) for r in self.results]
        return payload


def historical_case_ids(conn: "Connection", family: str = "returns.missing_accessory") -> list[str]:
    """The labeled corpus this family replays against."""
    return [case_id for case_id, _, _ in spec_for(family).corpus(conn)]


def replay_candidate_policy(
    conn: "Connection",
    definition: PolicyDefinition,
    case_ids: list[str] | None = None,
    *,
    enforce_coverage: bool = True,
) -> ReplayReport:
    """Evaluate a candidate against history. Read-only.

    `enforce_coverage` is the one part of this gate that is about quality rather
    than safety. A coverage floor stops the *agent* proposing a policy that looks
    safe because it does nothing. It must not stop a *person* deciding to
    automate less than the agent suggested — refusing a human who wants to be
    more conservative is exactly backwards. So a human revision that is no wider
    than the version it revises is exempt from the floor.

    Nothing exempts anything from the rules that matter: zero false automatic
    actions, and a policy that automates nothing at all is still not activatable.
    """
    spec = spec_for(definition.family)
    labels = {case_id: (label, note) for case_id, label, note in spec.corpus(conn)}
    ids = case_ids if case_ids is not None else list(labels)

    results: list[ReplayCaseResult] = []
    correct_auto = correct_escalate = false_auto = missed = 0

    for case_id in ids:
        # A case with no ground-truth label is treated as one that should escalate,
        # so an unlabeled case can never count as a successful automation.
        expected, note = labels.get(case_id, (LABEL_ESCALATE, ""))

        reasons: list[str] = []
        try:
            facts = spec.derive_facts(conn, case_id)
        except Exception as exc:  # a synthetic-system failure always escalates
            results.append(
                ReplayCaseResult(
                    case_id=case_id,
                    expected=expected,
                    predicted=LABEL_ESCALATE,
                    correct=expected == LABEL_ESCALATE,
                    reasons=[f"fact derivation failed: {exc}"],
                    scenario_note=note,
                )
            )
            if expected == LABEL_ESCALATE:
                correct_escalate += 1
            else:
                missed += 1
            continue

        guard = spec.guardrails(facts, matching_policy_count=1)
        if guard.blocked:
            predicted = LABEL_ESCALATE
            reasons.extend(guard.reasons)
        else:
            match = match_policy(definition, facts)
            if match.matched:
                predicted = LABEL_AUTO
            else:
                predicted = LABEL_ESCALATE
                reasons.extend(f"policy condition not met: {u}" for u in match.unmet)

        correct = predicted == expected
        if predicted == LABEL_AUTO and expected == LABEL_AUTO:
            correct_auto += 1
        elif predicted == LABEL_ESCALATE and expected == LABEL_ESCALATE:
            correct_escalate += 1
        elif predicted == LABEL_AUTO and expected == LABEL_ESCALATE:
            false_auto += 1
        else:
            missed += 1

        results.append(
            ReplayCaseResult(
                case_id=case_id,
                expected=expected,
                predicted=predicted,
                correct=correct,
                reasons=reasons[:6],
                scenario_note=note,
            )
        )

    auto_labeled = sum(1 for r in results if r.expected == LABEL_AUTO)
    coverage = (correct_auto / auto_labeled) if auto_labeled else 0.0

    blocking: list[str] = []
    if false_auto > 0:
        blocking.append(
            f"{false_auto} case(s) would have been actioned automatically but should escalate"
        )
    if correct_auto == 0:
        blocking.append("policy automates nothing on the historical set")
    if enforce_coverage and auto_labeled and coverage < MIN_AUTOMATION_COVERAGE:
        blocking.append(
            f"automation coverage {coverage:.0%} is below the required "
            f"{MIN_AUTOMATION_COVERAGE:.0%}"
        )

    return ReplayReport(
        policy_name=definition.name,
        cases_replayed=len(results),
        correct_auto_resolutions=correct_auto,
        correct_escalations=correct_escalate,
        false_automatic_actions=false_auto,
        missed_automations=missed,
        automation_coverage=round(coverage, 4),
        coverage_floor_enforced=enforce_coverage,
        passed=not blocking,
        blocking_reasons=blocking,
        failures=[
            {
                "case_id": r.case_id,
                "expected": r.expected,
                "predicted": r.predicted,
                "reasons": r.reasons,
                "scenario_note": r.scenario_note,
            }
            for r in results
            if not r.correct
        ],
        results=results,
    )
