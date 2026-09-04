#!/usr/bin/env python3
"""Run the OneDecision golden path end to end in the terminal.

    unknown exception -> agent investigates -> decision card -> human approves
    -> constrained policy proposal -> replay -> human activates
    -> next matching case resolves automatically -> verification -> audit

Run: python scripts/run_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import audit, db, seed  # noqa: E402
from app.agent.providers import provider_label  # noqa: E402
from app.config import settings  # noqa: E402
from app.domain import Outcome  # noqa: E402
from app.orchestrator import activate_policy, approve_and_teach, handle_event  # noqa: E402

RULE = "=" * 78
OPERATOR = "dana.r@northgate-optics.example"


def head(n: int, title: str) -> None:
    print(f"\n{RULE}\n{n}. {title}\n{RULE}")


def main() -> int:
    seed.seed(reset=True)
    print(f"provider : {provider_label()}")
    print(f"database : {db.db_path()}")

    # ---------------------------------------------------------------- case 1
    head(1, "CASE-2001 arrives as an event. Nothing knows what to do with it.")
    first = handle_event("CASE-2001")
    print(f"tool calls  : {', '.join(first.tool_calls)}")
    print(f"outcome     : {first.outcome}  (status {first.status})")
    if first.report:
        print(f"confidence  : {first.report.confidence}")
        print(f"rationale   : {first.report.rationale}")
    if first.decision_card is None:
        print("FAILED: expected a decision card")
        return 1
    card = first.decision_card
    print(f"\ndecision card: {card.headline}")
    print(f"  recommended : {card.recommended_action}")
    print("  boundaries  :")
    for b in card.proposed_boundaries:
        print(f"    - {b.description}")
    print(f"  needs a human because: {card.why_human_must_decide}")

    # ---------------------------------------------------------------- teach
    head(2, "The supervisor clicks Approve and Teach.")
    with db.session() as conn:
        teach = approve_and_teach(conn, first.exception_id, decided_by=OPERATOR)
    print(f"candidate policy : {teach.policy_id}  '{teach.definition.name}'")
    print("  conditions     :")
    for c in teach.definition.condition_summary():
        print(f"    - {c}")
    print("  actions        :")
    for a in teach.definition.action_summary():
        print(f"    - {a}")
    r = teach.replay
    print(
        f"\nreplay over {r['cases_replayed']} historical cases: "
        f"{r['correct_auto_resolutions']} correctly automated, "
        f"{r['correct_escalations']} correctly escalated, "
        f"{r['false_automatic_actions']} wrongly actioned"
    )
    print(f"replay passed    : {r['passed']}   ready to activate: {teach.ready_to_activate}")

    # ------------------------------------------------------------- activate
    head(3, "The supervisor explicitly activates the policy version.")
    with db.session() as conn:
        activated = activate_policy(
            conn,
            teach.policy_id,
            approval_token=settings.approval_token,
            activated_by=OPERATOR,
        )
    print(f"active policy    : {activated.label}  (activated by {activated.activated_by})")

    # ---------------------------------------------------------------- case 2
    head(4, "CASE-2002 arrives. It matches. Nobody is interrupted.")
    second = handle_event("CASE-2002")
    print(f"tool calls  : {', '.join(second.tool_calls)}")
    print(f"outcome     : {second.outcome}  (status {second.status})")
    print(f"policy      : {second.policy_id}")
    for a in second.actions:
        print(f"  action    : {a.action} -> {a.detail}")
    if second.verification:
        for c in second.verification.checks:
            print(f"  verified  : {c}")

    # ---------------------------------------------------------------- case 3
    head(5, "CASE-2003 looks almost identical. It is not. It escalates.")
    third = handle_event("CASE-2003")
    print(f"tool calls  : {', '.join(third.tool_calls)}")
    print(f"outcome     : {third.outcome}  (status {third.status})")
    for reason in third.escalation_reasons:
        print(f"  reason    : {reason}")

    # ----------------------------------------------------------- boundaries
    head(6, "Three more near-misses. All refused.")
    for case_id in ("CASE-2004", "CASE-2005", "CASE-2006"):
        result = handle_event(case_id)
        print(f"{case_id}: {result.outcome} — {result.escalation_reasons[0] if result.escalation_reasons else '?'}")

    # ---------------------------------------------------------------- audit
    head(7, "The audit trail.")
    with db.read_only() as conn:
        chain = audit.verify_chain(conn)
        entries = audit.read_for_case(conn, "CASE-2002")
    print(f"hash chain: {chain.detail} ({chain.entries_checked} entries)\n")
    print("CASE-2002 timeline (the case nobody was interrupted for):")
    for e in entries:
        detail = e.payload.get("detail") or e.payload.get("action") or e.payload.get("tool") or ""
        print(f"  {e.created_at}  {e.event_type:<28} {e.actor:<12} {str(detail)[:46]}")

    # ---------------------------------------------------------------- gate
    head(8, "Result.")
    ok = (
        first.outcome is Outcome.DECISION_REQUESTED
        and second.outcome is Outcome.AUTO_RESOLVED
        and third.outcome is Outcome.ESCALATED
        and chain.ok
    )
    print("GOLDEN PATH PASSED" if ok else "GOLDEN PATH FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
