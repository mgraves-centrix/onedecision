"""Evaluation harness.

Runs the whole product over the fixed synthetic case set and reports what
actually happened. Nothing here is estimated or asserted — every number is
counted from the database after the run.

  python -m app.evaluation --write-report
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import audit, db, seed
from app.adapters.warehouse import ALLOWED_DISPOSITIONS, ALLOWED_WORK_ORDER_TYPES
from app.agent.providers import provider_label
from app.config import REPO_ROOT, settings
from app.domain import Outcome
from app.orchestrator import activate_policy, approve_and_teach, handle_event

TEACHING_CASE = "CASE-2001"
OPERATOR = "dana.r@northgate-optics.example"

LABEL_AUTO = "auto_resolve"
LABEL_ESCALATE = "escalate"


@dataclass
class CaseOutcome:
    case_id: str
    expected: str
    outcome: str
    correct: bool
    duration_ms: int
    tool_calls: int
    reasons: list[str] = field(default_factory=list)
    scenario_note: str = ""


@dataclass
class EvaluationResult:
    provider: str
    generated_at: str
    cases_evaluated: int
    task_completion_rate: float
    correct_auto_resolution_rate: float
    correct_escalation_rate: float
    false_automatic_actions: int
    prohibited_actions: int
    duplicate_actions: int
    missed_automations: int
    avg_workflow_latency_ms: float
    p95_workflow_latency_ms: float
    avg_tool_latency_ms: float
    avg_tool_calls_per_case: float
    audit_chain_ok: bool
    audit_entries: int
    policy_version: str
    replay: dict[str, Any]
    outcomes: list[CaseOutcome] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["outcomes"] = [asdict(o) for o in self.outcomes]
        return payload


def _expected_outcome(label: str) -> set[Outcome]:
    """A labeled `escalate` case is handled correctly if it does not act automatically."""
    if label == LABEL_AUTO:
        return {Outcome.AUTO_RESOLVED}
    return {Outcome.ESCALATED, Outcome.DECISION_REQUESTED}


def run_evaluation(reset: bool = True) -> EvaluationResult:
    if reset:
        seed.seed(reset=True)

    tool_latencies: list[float] = []

    with db.session() as conn:
        # ---------------------------------------------- teach and activate
        first = handle_event(TEACHING_CASE, conn=conn)
        if first.outcome is not Outcome.DECISION_REQUESTED:
            raise RuntimeError(f"teaching case did not request a decision: {first.outcome}")
        teach = approve_and_teach(conn, first.exception_id, decided_by=OPERATOR)
        activated = activate_policy(
            conn, teach.policy_id, approval_token=settings.approval_token, activated_by=OPERATOR
        )

        # ---------------------------------------------------- run the set
        rows = conn.execute(
            """SELECT case_id, expected_label, scenario_note FROM return_cases
                WHERE is_historical = 1 ORDER BY case_id"""
        ).fetchall()

        outcomes: list[CaseOutcome] = []
        for row in rows:
            started = time.perf_counter()
            result = handle_event(row["case_id"], conn=conn)
            elapsed = (time.perf_counter() - started) * 1000
            if result.tool_calls:
                tool_latencies.append(elapsed / len(result.tool_calls))
            outcomes.append(
                CaseOutcome(
                    case_id=row["case_id"],
                    expected=row["expected_label"],
                    outcome=result.outcome.value,
                    correct=result.outcome in _expected_outcome(row["expected_label"]),
                    duration_ms=int(elapsed),
                    tool_calls=len(result.tool_calls),
                    reasons=result.escalation_reasons[:3],
                    scenario_note=row["scenario_note"],
                )
            )

        # ------------------------------- replay every case as a duplicate
        work_orders_before = conn.execute("SELECT COUNT(*) c FROM work_orders").fetchone()["c"]
        for row in rows:
            handle_event(row["case_id"], conn=conn)
        work_orders_after = conn.execute("SELECT COUNT(*) c FROM work_orders").fetchone()["c"]
        duplicate_actions = work_orders_after - work_orders_before

        # ------------------------------------------------------- counting
        auto_labeled = [o for o in outcomes if o.expected == LABEL_AUTO]
        esc_labeled = [o for o in outcomes if o.expected == LABEL_ESCALATE]

        false_auto = sum(
            1 for o in outcomes if o.expected == LABEL_ESCALATE and o.outcome == "auto_resolved"
        )
        missed = sum(
            1 for o in outcomes if o.expected == LABEL_AUTO and o.outcome != "auto_resolved"
        )

        prohibited = 0
        for disp in conn.execute("SELECT disposition FROM dispositions").fetchall():
            if disp["disposition"] not in ALLOWED_DISPOSITIONS:
                prohibited += 1
        for wo in conn.execute("SELECT work_order_type, cost_usd FROM work_orders").fetchall():
            if wo["work_order_type"] not in ALLOWED_WORK_ORDER_TYPES:
                prohibited += 1
            if wo["cost_usd"] > activated.definition.actions[1].max_cost_usd:  # type: ignore[union-attr]
                prohibited += 1

        chain = audit.verify_chain(conn)
        latencies = [o.duration_ms for o in outcomes]

        return EvaluationResult(
            provider=provider_label(),
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            cases_evaluated=len(outcomes),
            task_completion_rate=round(sum(o.correct for o in outcomes) / len(outcomes), 4),
            correct_auto_resolution_rate=round(
                sum(1 for o in auto_labeled if o.outcome == "auto_resolved") / len(auto_labeled),
                4,
            )
            if auto_labeled
            else 0.0,
            correct_escalation_rate=round(
                sum(1 for o in esc_labeled if o.outcome != "auto_resolved") / len(esc_labeled), 4
            )
            if esc_labeled
            else 0.0,
            false_automatic_actions=false_auto,
            prohibited_actions=prohibited,
            duplicate_actions=duplicate_actions,
            missed_automations=missed,
            avg_workflow_latency_ms=round(statistics.mean(latencies), 2),
            p95_workflow_latency_ms=round(
                sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2
            ),
            avg_tool_latency_ms=round(statistics.mean(tool_latencies), 2) if tool_latencies else 0.0,
            avg_tool_calls_per_case=round(
                statistics.mean([o.tool_calls for o in outcomes]), 2
            ),
            audit_chain_ok=chain.ok,
            audit_entries=chain.entries_checked,
            policy_version=activated.label,
            replay=teach.replay,
            outcomes=outcomes,
        )


REPORT_HEADER = """# OneDecision — Evaluation Results

Generated by `python -m app.evaluation --write-report`. Every number below is
counted from the database after an actual run over the fixed synthetic case set.
Nothing here is estimated.
"""


def render_report(result: EvaluationResult) -> str:
    r = result
    lines = [
        REPORT_HEADER,
        f"- **Run at:** {r.generated_at}",
        f"- **Model provider:** {r.provider}",
        f"- **Policy under evaluation:** `{r.policy_version}`",
        f"- **Cases evaluated:** {r.cases_evaluated} (fixed synthetic historical set)",
        "",
        "## Headline metrics",
        "",
        "| Metric | Result | Target |",
        "| --- | --- | --- |",
        f"| Task-completion rate | {r.task_completion_rate:.1%} | high |",
        f"| Correct auto-resolution rate | {r.correct_auto_resolution_rate:.1%} | high |",
        f"| Correct-escalation rate | {r.correct_escalation_rate:.1%} | 100% |",
        f"| **False automatic actions** | **{r.false_automatic_actions}** | **0** |",
        f"| **Prohibited actions** | **{r.prohibited_actions}** | **0** |",
        f"| **Duplicate actions** | **{r.duplicate_actions}** | **0** |",
        f"| Missed automations | {r.missed_automations} | low |",
        "",
        "## Latency",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Average end-to-end workflow | {r.avg_workflow_latency_ms:.1f} ms |",
        f"| p95 end-to-end workflow | {r.p95_workflow_latency_ms:.1f} ms |",
        f"| Average per tool call | {r.avg_tool_latency_ms:.1f} ms |",
        f"| Average tool calls per case | {r.avg_tool_calls_per_case:.2f} |",
        "",
        "Latency is measured against the deterministic offline provider, so these",
        "figures show the cost of the orchestration, the guardrails, the policy",
        "engine, and the audit log — not of model inference. A hosted model adds its",
        "own latency on top and is measured separately.",
        "",
        "## Replay gate on the taught policy",
        "",
        f"- Cases replayed: {r.replay['cases_replayed']}",
        f"- Correctly automated: {r.replay['correct_auto_resolutions']}",
        f"- Correctly escalated: {r.replay['correct_escalations']}",
        f"- Wrongly actioned: **{r.replay['false_automatic_actions']}**",
        f"- Automation coverage: {r.replay['automation_coverage']:.0%}",
        f"- Replay passed: {r.replay['passed']}",
        "",
        "## Audit integrity",
        "",
        f"- Entries written: {r.audit_entries}",
        f"- Hash chain intact: {r.audit_chain_ok}",
        "",
        "## Per-case outcomes",
        "",
        "| Case | Expected | Outcome | Correct | ms | Notes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for o in r.outcomes:
        mark = "yes" if o.correct else "**NO**"
        lines.append(
            f"| `{o.case_id}` | {o.expected} | {o.outcome} | {mark} | {o.duration_ms} | {o.scenario_note} |"
        )

    lines += [
        "",
        "## Reading these numbers",
        "",
        "The metric that matters is **false automatic actions**: cases the system",
        "acted on by itself that a person should have seen. The target is zero and",
        "the design treats it as a hard constraint, not an average — the guardrails",
        "run before any policy, the replay gate blocks activation on a single false",
        "action, and the action adapters enforce the spend cap a second time at the",
        "point of write.",
        "",
        "**Missed automations** are the acceptable failure. A case that escalates",
        "when it could have been handled costs a supervisor two minutes. A case that",
        "is actioned wrongly costs a camera.",
        "",
        "Cases labeled `escalate` are scored as correct when the system either",
        "escalates them or asks for a human decision — both mean it did not act on",
        "its own.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the OneDecision evaluation harness.")
    parser.add_argument("--write-report", action="store_true", help="write docs/evaluation-results.md")
    parser.add_argument("--json", action="store_true", help="print raw JSON")
    args = parser.parse_args()

    result = run_evaluation()

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        print(f"provider                     : {result.provider}")
        print(f"cases evaluated              : {result.cases_evaluated}")
        print(f"task completion rate         : {result.task_completion_rate:.1%}")
        print(f"correct auto-resolution rate : {result.correct_auto_resolution_rate:.1%}")
        print(f"correct escalation rate      : {result.correct_escalation_rate:.1%}")
        print(f"false automatic actions      : {result.false_automatic_actions}")
        print(f"prohibited actions           : {result.prohibited_actions}")
        print(f"duplicate actions            : {result.duplicate_actions}")
        print(f"missed automations           : {result.missed_automations}")
        print(f"avg workflow latency         : {result.avg_workflow_latency_ms:.1f} ms")
        print(f"avg tool latency             : {result.avg_tool_latency_ms:.1f} ms")
        print(f"audit chain intact           : {result.audit_chain_ok} ({result.audit_entries} entries)")

    if args.write_report:
        path = REPO_ROOT / "docs" / "evaluation-results.md"
        path.write_text(render_report(result))
        print(f"\nwrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
