"""Replay a candidate policy against labelled historical cases.

Replay is a **dry run**: it derives facts, evaluates the guardrails and the
candidate policy, and compares the predicted outcome against the recorded
ground-truth label. It never writes to a business system.

Activation is blocked unless replay passes. The bar is deliberately blunt:
zero false automatic actions, and the policy must actually automate something.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Any

from app.facts import derive_facts
from app.policy.guardrails import evaluate_guardrails
from app.policy.engine import match_policy
from app.policy.schema import PolicyDefinition

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
    passed: bool
    blocking_reasons: list[str] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    results: list[ReplayCaseResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["results"] = [asdict(r) for r in self.results]
        return payload


def historical_case_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT case_id FROM return_cases WHERE is_historical = 1 ORDER BY case_id"
    ).fetchall()
    return [r["case_id"] for r in rows]


def replay_candidate_policy(
    conn: sqlite3.Connection, definition: PolicyDefinition, case_ids: list[str] | None = None
) -> ReplayReport:
    """Evaluate a candidate against history. Read-only."""
    ids = case_ids if case_ids is not None else historical_case_ids(conn)

    results: list[ReplayCaseResult] = []
    correct_auto = correct_escalate = false_auto = missed = 0

    for case_id in ids:
        row = conn.execute(
            "SELECT expected_label, scenario_note FROM return_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        expected = row["expected_label"] if row else LABEL_ESCALATE
        note = row["scenario_note"] if row else ""

        reasons: list[str] = []
        try:
            facts = derive_facts(conn, case_id)
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

        guard = evaluate_guardrails(facts, matching_policy_count=1)
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

    auto_labelled = sum(1 for r in results if r.expected == LABEL_AUTO)
    coverage = (correct_auto / auto_labelled) if auto_labelled else 0.0

    blocking: list[str] = []
    if false_auto > 0:
        blocking.append(
            f"{false_auto} case(s) would have been actioned automatically but should escalate"
        )
    if correct_auto == 0:
        blocking.append("policy automates nothing on the historical set")
    if auto_labelled and coverage < MIN_AUTOMATION_COVERAGE:
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
