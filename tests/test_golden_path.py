"""The whole product, end to end, three times over."""

from __future__ import annotations

import pytest

from app import audit, db
from app.domain import ExceptionStatus, Outcome
from app.orchestrator import activate_policy, approve_and_teach, handle_event
from app.policy import store

OPERATOR = "dana.r@northgate-optics.example"


@pytest.fixture()
def taught(conn, approval_token):
    """Walk the golden path up to an activated policy version."""
    first = handle_event("CASE-2001", conn=conn)
    assert first.outcome is Outcome.DECISION_REQUESTED
    teach = approve_and_teach(conn, first.exception_id, decided_by=OPERATOR)
    activate_policy(conn, teach.policy_id, approval_token=approval_token, activated_by=OPERATOR)
    return first, teach


def test_unknown_case_produces_a_decision_card(conn):
    result = handle_event("CASE-2001", conn=conn)
    assert result.outcome is Outcome.DECISION_REQUESTED
    assert result.status is ExceptionStatus.WAITING_DECISION
    assert result.decision_card is not None
    card = result.decision_card
    assert card.case_id == "CASE-2001"
    assert card.evidence and card.proposed_boundaries and card.why_human_must_decide
    assert result.tool_calls == [
        "get_return_case",
        "compare_expected_and_received",
        "lookup_replacement_cost",
        "find_approved_policy",
    ]


def test_no_action_is_taken_while_waiting_for_a_decision(conn):
    handle_event("CASE-2001", conn=conn)
    assert conn.execute("SELECT COUNT(*) c FROM work_orders").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM dispositions").fetchone()["c"] == 0


def test_approval_produces_a_candidate_not_an_active_policy(conn):
    first = handle_event("CASE-2001", conn=conn)
    teach = approve_and_teach(conn, first.exception_id, decided_by=OPERATOR)
    assert store.get(conn, teach.policy_id).status == "candidate"
    assert store.list_active(conn) == []
    assert teach.replay["passed"] is True
    assert teach.replay["false_automatic_actions"] == 0


def test_activation_makes_the_policy_live(conn, taught):
    _first, teach = taught
    active = store.list_active(conn)
    assert [p.policy_id for p in active] == [teach.policy_id]
    assert active[0].activated_by == OPERATOR


def test_matching_case_resolves_automatically(conn, taught):
    _first, teach = taught
    result = handle_event("CASE-2002", conn=conn)
    assert result.outcome is Outcome.AUTO_RESOLVED
    assert result.status is ExceptionStatus.RESOLVED
    assert result.policy_id == teach.policy_id
    assert [a.action for a in result.actions] == [
        "set_disposition:PARTS_HOLD",
        "create_work_order:REPLACEMENT_PARTS",
        "close_exception:RESOLVED_PARTS_REPLACEMENT",
    ]
    assert result.verification is not None and result.verification.ok
    assert result.decision_card is None  # nobody was interrupted


def test_the_automatic_action_actually_landed(conn, taught):
    handle_event("CASE-2002", conn=conn)
    wo = conn.execute("SELECT * FROM work_orders WHERE case_id = 'CASE-2002'").fetchall()
    assert len(wo) == 1
    assert wo[0]["work_order_type"] == "REPLACEMENT_PARTS"
    assert wo[0]["component_id"] == "CMP-CAP-BODY"
    assert wo[0]["cost_usd"] == 6.50
    disp = conn.execute("SELECT * FROM dispositions WHERE case_id = 'CASE-2002'").fetchone()
    assert disp["disposition"] == "PARTS_HOLD"


@pytest.mark.parametrize(
    "case_id,fragment",
    [
        ("CASE-2003", "serial number does not match"),
        ("CASE-2005", "new damage"),
        ("CASE-2006", "tool failure"),
    ],
)
def test_risky_near_matches_still_escalate(conn, taught, case_id, fragment):
    result = handle_event(case_id, conn=conn)
    assert result.outcome is Outcome.ESCALATED
    assert any(fragment in r for r in result.escalation_reasons), result.escalation_reasons
    assert conn.execute(
        "SELECT COUNT(*) c FROM work_orders WHERE case_id = ?", (case_id,)
    ).fetchone()["c"] == 0


def test_a_case_over_the_taught_threshold_escalates(conn, taught):
    result = handle_event("CASE-2004", conn=conn)
    assert result.outcome is Outcome.ESCALATED
    assert any("replacement_cost_usd" in r for r in result.escalation_reasons)


def test_duplicate_events_do_not_act_twice(conn, taught):
    first = handle_event("CASE-2002", conn=conn, event_key="evt-fixed")
    second = handle_event("CASE-2002", conn=conn, event_key="evt-fixed")
    assert first.exception_id == second.exception_id
    assert conn.execute(
        "SELECT COUNT(*) c FROM work_orders WHERE case_id = 'CASE-2002'"
    ).fetchone()["c"] == 1
    types = [e.event_type for e in audit.read_for_case(conn, "CASE-2002")]
    assert "event.duplicate_suppressed" in types


def test_reexecuting_the_same_policy_is_idempotent(conn, taught):
    from app.facts import derive_facts
    from app.orchestrator import execute_approved_policy, idempotency_key

    _first, teach = taught
    result = handle_event("CASE-2002", conn=conn)
    facts = derive_facts(conn, "CASE-2002")
    record = store.get(conn, teach.policy_id)
    key = idempotency_key("CASE-2002", teach.policy_id, str(record.version))

    again = execute_approved_policy(
        conn, "CASE-2002", teach.policy_id, key,
        trace_id="trc_retry", exception_id=result.exception_id, facts=facts,
    )
    assert all(a.ok for a in again)
    assert any(a.duplicate_suppressed for a in again)
    assert conn.execute(
        "SELECT COUNT(*) c FROM work_orders WHERE case_id = 'CASE-2002'"
    ).fetchone()["c"] == 1


def test_a_candidate_policy_can_never_execute(conn):
    from app.facts import derive_facts
    from app.orchestrator import OrchestratorError, execute_approved_policy

    first = handle_event("CASE-2001", conn=conn)
    teach = approve_and_teach(conn, first.exception_id, decided_by=OPERATOR)
    with pytest.raises(OrchestratorError) as exc:
        execute_approved_policy(
            conn, "CASE-2002", teach.policy_id, "key",
            trace_id="t", exception_id=first.exception_id,
            facts=derive_facts(conn, "CASE-2002"),
        )
    assert "not 'active'" in str(exc.value)


def test_activation_resolves_the_case_that_taught_the_policy(conn, taught):
    """The supervisor approved the action, so the origin case is acted on too."""
    first, teach = taught
    row = conn.execute(
        "SELECT status, applied_policy_id FROM exceptions WHERE exception_id = ?",
        (first.exception_id,),
    ).fetchone()
    assert row["status"] == ExceptionStatus.RESOLVED
    assert row["applied_policy_id"] == teach.policy_id

    wo = conn.execute(
        "SELECT * FROM work_orders WHERE case_id = 'CASE-2001'"
    ).fetchall()
    assert len(wo) == 1
    assert wo[0]["component_id"] == "CMP-STRAP-NEO"
    assert wo[0]["cost_usd"] == 14.00


def test_activation_does_not_resolve_a_case_that_no_longer_qualifies(conn, approval_token):
    """If the facts change between the decision and activation, it escalates."""
    first = handle_event("CASE-2001", conn=conn)
    teach = approve_and_teach(conn, first.exception_id, decided_by=OPERATOR)
    conn.execute("UPDATE return_cases SET new_damage_present = 1 WHERE case_id = 'CASE-2001'")

    activate_policy(conn, teach.policy_id, approval_token=approval_token, activated_by=OPERATOR)
    row = conn.execute(
        "SELECT status FROM exceptions WHERE exception_id = ?", (first.exception_id,)
    ).fetchone()
    assert row["status"] == ExceptionStatus.ESCALATED
    assert conn.execute(
        "SELECT COUNT(*) c FROM work_orders WHERE case_id = 'CASE-2001'"
    ).fetchone()["c"] == 0
