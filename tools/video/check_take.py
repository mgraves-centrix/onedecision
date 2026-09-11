"""Confirm a recorded take matches what the narration says happened.

Usage: python tools/video/check_take.py <take.db>
Exits nonzero when a claim in the voiceover would be false for this take, so a
take like that gets re-recorded instead of assembled.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys

db = sqlite3.connect(sys.argv[1])
db.row_factory = sqlite3.Row

exceptions = {r["case_id"]: r for r in db.execute("SELECT * FROM exceptions")}
policies = list(db.execute("SELECT policy_id, family, version, status, origin_case_id, replay_report FROM policies"))
dispositions = {r["case_id"]: r["disposition"] for r in db.execute("SELECT * FROM dispositions")}
work_orders = list(db.execute("SELECT case_id, work_order_type, component_id, cost_usd, status FROM work_orders"))

print("exceptions:")
for case_id, r in sorted(exceptions.items()):
    reasons = json.loads(r["escalation_reasons"] or "[]")
    print(f"  {case_id}  {r['status']:<18} policy={r['applied_policy_id'] or '-'}  reasons={len(reasons)}")
print("policies:")
for p in policies:
    print(f"  {p['policy_id']}  {p['family']} v{p['version']}  {p['status']}  from {p['origin_case_id']}")
print("dispositions:", dispositions or "-")
print("work orders:")
for w in work_orders:
    print(f"  {w['case_id']}  {w['work_order_type']} {w['component_id']} ${w['cost_usd']:.2f}  {w['status']}")

active = [p for p in policies if p["status"] == "active"]


def events(case_id: str, event_type: str) -> list[dict]:
    return [json.loads(r[0]) for r in db.execute(
        "SELECT payload FROM audit_log WHERE case_id = ? AND event_type = ? ORDER BY seq", (case_id, event_type))]


def work_order(case_id: str) -> tuple[str, float] | None:
    return next(((w["component_id"], w["cost_usd"]) for w in work_orders if w["case_id"] == case_id), None)


first_tools = [e.get("tool") for e in events("CASE-2001", "tool.called")[:4]]
card_row = db.execute(
    "SELECT d.payload FROM decision_cards d JOIN exceptions e USING (exception_id) WHERE e.case_id = 'CASE-2001'"
).fetchone()
card_2001 = card_row[0] if card_row else None
if card_2001:
    print("\nCASE-2001 card recommends:", json.loads(card_2001).get("recommended_action"))
replay = json.loads(active[0]["replay_report"] or "{}") if active else {}
e2002, e2003 = exceptions.get("CASE-2002"), exceptions.get("CASE-2003")
checks = {
    "CASE-2001 decided by a human": "CASE-2001" in exceptions
        and db.execute(
            "SELECT 1 FROM decision_cards d JOIN exceptions e USING (exception_id) "
            "WHERE e.case_id = 'CASE-2001' AND d.outcome IS NOT NULL"
        ).fetchone() is not None,
    "one policy active, taught from CASE-2001": len(active) == 1 and active[0]["origin_case_id"] == "CASE-2001",
    "CASE-2002 resolved under that policy": e2002 is not None
        and bool(active) and e2002["applied_policy_id"] == active[0]["policy_id"]
        and e2002["status"] not in ("escalated", "waiting_decision"),
    "CASE-2003 escalated to a person": e2003 is not None and e2003["status"] == "escalated",
    # The specifics the voiceover states out loud.
    "arrive: four read-only tool calls, in order": first_tools == [
        "get_return_case", "compare_expected_and_received", "lookup_replacement_cost", "find_approved_policy"],
    "arrive: one neoprene strap, $14": work_order("CASE-2001") == ("CMP-STRAP-NEO", 14.0),
    "teach: 24 cases replayed, zero false automatic actions": replay.get("cases_replayed") == 24
        and replay.get("false_automatic_actions") == 0 and replay.get("passed") is True,
    "next: body cap, writes verified, closed": work_order("CASE-2002") == ("CMP-CAP-BODY", 6.5)
        and bool(events("CASE-2002", "verification.passed")) and bool(events("CASE-2002", "exception.resolved")),
    "boundary: guardrail blocked on the serial": bool(events("CASE-2003", "guardrail.blocked"))
        and e2003 is not None and "serial" in e2003["escalation_reasons"],
    # The voiceover says approving "activates nothing"; the card on screen must agree.
    "arrive: the card does not claim approval activates anything": card_2001 is not None
        and not re.search(r"approv\w*\s+(also\s+)?(will\s+)?activat", card_2001, re.I),
}
print()
for name, ok in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
sys.exit(0 if all(checks.values()) else 1)
