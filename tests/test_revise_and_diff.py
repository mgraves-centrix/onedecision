"""The revise control and the policy diff.

The brief specified both under the Decision and Replay view. The interesting
question for revise is not "can a human edit a policy" but "what can a human
edit it *into*" — the answer has to stay inside the guardrails, and it has to be
re-proved by replay rather than trusted.
"""

from __future__ import annotations

import pytest

from app import audit, db
from app.config import MAX_REPLACEMENT_COST_CEILING_USD
from app.domain import PolicyStatus
from app.orchestrator import (
    OrchestratorError,
    activate_policy,
    approve_and_teach,
    handle_event,
    policy_diff_for,
    revise_candidate,
)
from app.policy import store
from app.policy.diff import ChangeKind, diff_policies
from app.policy.proposal import revised_payload
from app.policy.schema import PolicyValidationError, validate_policy_payload
from tests.conftest import demo_policy_payload

OPERATOR = "dana.r@northgate-optics.example"


@pytest.fixture()
def candidate(conn):
    first = handle_event("CASE-2001", conn=conn)
    return first, approve_and_teach(conn, first.exception_id, decided_by=OPERATOR)


# --------------------------------------------------------------------- diff


def test_diff_against_no_active_policy_is_all_new(conn):
    policy = validate_policy_payload(demo_policy_payload())
    d = diff_policies(None, policy)
    assert d.has_changes
    assert all(r.kind is ChangeKind.ADDED for r in d.rows)
    assert not d.widens  # adding conditions never widens


def test_diff_flags_a_raised_cap_as_widening(conn):
    base = validate_policy_payload(demo_policy_payload())
    payload = demo_policy_payload()
    payload["conditions"][-1]["value"] = 40.0
    payload["actions"][1]["max_cost_usd"] = 40.0
    d = diff_policies(base, validate_policy_payload(payload))
    assert d.widens
    assert {r.kind for r in d.changed_rows} == {ChangeKind.WIDENED}


def test_diff_flags_a_lowered_cap_as_narrowing(conn):
    base = validate_policy_payload(demo_policy_payload())
    payload = demo_policy_payload()
    payload["conditions"][-1]["value"] = 10.0
    payload["actions"][1]["max_cost_usd"] = 10.0
    d = diff_policies(base, validate_policy_payload(payload))
    assert not d.widens
    assert all(r.kind is ChangeKind.NARROWED for r in d.changed_rows)


def test_diff_treats_a_higher_confidence_floor_as_narrowing(conn):
    base = validate_policy_payload(demo_policy_payload())
    tighter = validate_policy_payload(demo_policy_payload(min_confidence=0.95))
    d = diff_policies(base, tighter)
    row = next(r for r in d.changed_rows if r.label == "minimum confidence")
    assert row.kind is ChangeKind.NARROWED
    looser = validate_policy_payload(demo_policy_payload(min_confidence=0.55))
    row = next(r for r in diff_policies(base, looser).changed_rows if r.label == "minimum confidence")
    assert row.kind is ChangeKind.WIDENED


def test_diff_reports_a_removed_condition_as_widening(conn):
    base = validate_policy_payload(demo_policy_payload())
    payload = demo_policy_payload()
    payload["conditions"] = [c for c in payload["conditions"] if c["field"] != "serial_match"]
    d = diff_policies(base, validate_policy_payload(payload))
    row = next(r for r in d.changed_rows if r.label == "serial_match")
    assert row.kind is ChangeKind.REMOVED
    assert d.widens


# ------------------------------------------------------------------ revise


def test_revision_creates_a_new_candidate_and_supersedes_the_original(conn, candidate):
    _first, teach = candidate
    revised = revise_candidate(
        conn, teach.policy_id, max_cost_usd=15.0, min_confidence=0.85,
        kit_category=None, revised_by=OPERATOR, note="tighter for now",
    )
    assert revised.policy_id != teach.policy_id
    assert store.get(conn, teach.policy_id).status == PolicyStatus.SUPERSEDED
    assert store.get(conn, revised.policy_id).status == PolicyStatus.CANDIDATE

    record = store.get(conn, revised.policy_id)
    assert record.revised_from_policy_id == teach.policy_id
    assert record.revision_note == "tighter for now"
    assert record.definition.spend_cap() == 15.0
    assert record.definition.min_confidence == 0.85


def test_the_original_proposal_is_never_edited(conn, candidate):
    """The record must keep what the agent proposed, not just what a human kept."""
    _first, teach = candidate
    original = store.get(conn, teach.policy_id).definition.model_dump_json()
    revise_candidate(
        conn, teach.policy_id, max_cost_usd=10.0, min_confidence=0.9,
        kit_category=None, revised_by=OPERATOR,
    )
    assert store.get(conn, teach.policy_id).definition.model_dump_json() == original


def test_a_revision_cannot_remove_a_safety_condition(conn, candidate):
    """There is no way to express it: the form carries no condition list."""
    _first, teach = candidate
    before = {c.field for c in store.get(conn, teach.policy_id).definition.conditions}
    revised = revise_candidate(
        conn, teach.policy_id, max_cost_usd=25.0, min_confidence=0.75,
        kit_category=None, revised_by=OPERATOR,
    )
    after = {c.field for c in revised.definition.conditions}
    assert before <= after
    for required in ("serial_match", "new_damage_present", "evidence_complete",
                     "missing_component_serialized", "missing_component_safety_critical"):
        assert required in after


def test_a_revision_cannot_exceed_the_hard_ceiling(conn, candidate):
    _first, teach = candidate
    revised = revise_candidate(
        conn, teach.policy_id, max_cost_usd=100_000.0, min_confidence=0.75,
        kit_category=None, revised_by=OPERATOR,
    )
    assert revised.definition.spend_cap() == MAX_REPLACEMENT_COST_CEILING_USD


def test_a_category_restriction_only_narrows(conn, candidate):
    _first, teach = candidate
    revised = revise_candidate(
        conn, teach.policy_id, max_cost_usd=25.0, min_confidence=0.75,
        kit_category="camera_kit", revised_by=OPERATOR,
    )
    assert revised.definition.kit_category_restriction() == "camera_kit"
    d = policy_diff_for(conn, store.get(conn, revised.policy_id))
    assert not d.widens


def test_a_revision_is_replayed_again_before_it_can_be_activated(conn, candidate):
    _first, teach = candidate
    revised = revise_candidate(
        conn, teach.policy_id, max_cost_usd=25.0, min_confidence=0.75,
        kit_category=None, revised_by=OPERATOR,
    )
    report = store.get(conn, revised.policy_id).replay_report
    assert report is not None
    assert report["false_automatic_actions"] == 0
    assert revised.ready_to_activate


def test_a_revision_that_automates_nothing_cannot_be_activated(conn, candidate, approval_token):
    """Tighten it into uselessness and the gate refuses, exactly as for a proposal."""
    _first, teach = candidate
    revised = revise_candidate(
        conn, teach.policy_id, max_cost_usd=0.01, min_confidence=0.75,
        kit_category=None, revised_by=OPERATOR,
    )
    assert not revised.ready_to_activate
    with pytest.raises(store.ActivationDenied) as exc:
        activate_policy(
            conn, revised.policy_id, approval_token=approval_token, activated_by=OPERATOR
        )
    assert "replay did not pass" in str(exc.value)


def test_a_superseded_candidate_can_no_longer_be_activated(conn, candidate, approval_token):
    _first, teach = candidate
    revise_candidate(
        conn, teach.policy_id, max_cost_usd=20.0, min_confidence=0.75,
        kit_category=None, revised_by=OPERATOR,
    )
    with pytest.raises(store.ActivationDenied) as exc:
        activate_policy(
            conn, teach.policy_id, approval_token=approval_token, activated_by=OPERATOR
        )
    assert "only a candidate may be activated" in str(exc.value)


def test_a_superseded_candidate_cannot_be_revised_again(conn, candidate):
    _first, teach = candidate
    revise_candidate(
        conn, teach.policy_id, max_cost_usd=20.0, min_confidence=0.75,
        kit_category=None, revised_by=OPERATOR,
    )
    with pytest.raises(OrchestratorError) as exc:
        revise_candidate(
            conn, teach.policy_id, max_cost_usd=18.0, min_confidence=0.75,
            kit_category=None, revised_by=OPERATOR,
        )
    assert "only a candidate may be revised" in str(exc.value)


def test_a_revised_policy_activates_and_enforces_its_new_cap(conn, candidate, approval_token):
    """Revise to $10, activate, and the $14 case must now escalate."""
    _first, teach = candidate
    revised = revise_candidate(
        conn, teach.policy_id, max_cost_usd=10.0, min_confidence=0.75,
        kit_category=None, revised_by=OPERATOR,
    )
    activate_policy(
        conn, revised.policy_id, approval_token=approval_token, activated_by=OPERATOR
    )
    # CASE-2002 costs $6.50 -> still automated.
    assert handle_event("CASE-2002", conn=conn).outcome.value == "auto_resolved"
    # CASE-1001 costs $14.00 -> now outside the revised boundary.
    result = handle_event("CASE-1001", conn=conn)
    assert result.outcome.value == "escalated"
    assert any("replacement_cost_usd" in r for r in result.escalation_reasons)


def test_the_revision_is_audited_with_its_diff(conn, candidate):
    _first, teach = candidate
    revise_candidate(
        conn, teach.policy_id, max_cost_usd=40.0, min_confidence=0.75,
        kit_category=None, revised_by=OPERATOR, note="raising it deliberately",
    )
    entries = audit.read_all(conn, limit=200)
    revised = next(e for e in entries if e.event_type == "policy.revised")
    assert revised.actor == OPERATOR
    assert revised.payload["widens"] is True
    assert revised.payload["note"] == "raising it deliberately"
    assert any(c["field"] == "spend cap" for c in revised.payload["changes"])
    assert any(e.event_type == "policy.superseded" for e in entries)


def test_lineage_reads_oldest_first(conn, candidate):
    _first, teach = candidate
    r1 = revise_candidate(conn, teach.policy_id, max_cost_usd=20.0, min_confidence=0.75,
                          kit_category=None, revised_by=OPERATOR)
    r2 = revise_candidate(conn, r1.policy_id, max_cost_usd=18.0, min_confidence=0.75,
                          kit_category=None, revised_by=OPERATOR)
    chain = store.revision_lineage(conn, r2.policy_id)
    assert [c.policy_id for c in chain] == [teach.policy_id, r1.policy_id, r2.policy_id]


# ------------------------------------------------------------------- the web


def test_revise_through_the_ui(temp_db, approval_token):
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        r = client.post("/events/CASE-2001", follow_redirects=True)
        exception_id = r.url.path.rsplit("/", 1)[-1]
        r = client.post(f"/exceptions/{exception_id}/approve", follow_redirects=True)
        assert "Revise before deciding" in r.text
        assert "What changes" in r.text

        with db.read_only() as conn:
            original = store.list_all(conn)[0]

        r = client.post(
            f"/policies/{original.policy_id}/revise",
            data={
                "max_cost_usd": "12.00",
                "min_confidence": "0.85",
                "kit_category": "camera_kit",
                "note": "camera kits only, lower cap",
                "redirect_to": f"/exceptions/{exception_id}",
            },
            follow_redirects=True,
        )
        assert r.status_code == 200
        assert "Revision history" in r.text
        assert "camera kits only, lower cap" in r.text

        with db.read_only() as conn:
            records = {p.policy_id: p for p in store.list_all(conn)}
        revision = next(p for p in records.values() if p.revised_from_policy_id)
        assert records[original.policy_id].status == PolicyStatus.SUPERSEDED
        assert revision.definition.spend_cap() == 12.00
        assert revision.definition.kit_category_restriction() == "camera_kit"


def test_the_ui_refuses_a_revision_of_an_already_activated_policy(temp_db, approval_token):
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        r = client.post("/events/CASE-2001", follow_redirects=True)
        exception_id = r.url.path.rsplit("/", 1)[-1]
        client.post(f"/exceptions/{exception_id}/approve", follow_redirects=True)
        with db.read_only() as conn:
            candidate_id = store.list_all(conn)[0].policy_id
        client.post(
            f"/policies/{candidate_id}/activate",
            data={"approval_token": approval_token},
            follow_redirects=True,
        )
        r = client.post(
            f"/policies/{candidate_id}/revise",
            data={"max_cost_usd": "40.00", "min_confidence": "0.75", "kit_category": "", "note": ""},
        )
        assert r.status_code == 400
        assert "only a candidate may be revised" in r.json()["detail"]


# ------------------------------------------------- the coverage-floor waiver


def test_a_narrowing_revision_is_exempt_from_the_coverage_floor(conn, candidate, approval_token):
    """A person choosing to automate less than the agent proposed must be allowed.

    The coverage floor exists to stop the agent proposing a policy that looks
    safe because it does nothing. Applying it to a human tightening the boundary
    would mean refusing someone who wants to be more careful.
    """
    from app.policy.replay import MIN_AUTOMATION_COVERAGE

    _first, teach = candidate
    revised = revise_candidate(
        conn, teach.policy_id, max_cost_usd=10.0, min_confidence=0.75,
        kit_category=None, revised_by=OPERATOR,
    )
    report = revised.replay
    assert report["automation_coverage"] < MIN_AUTOMATION_COVERAGE
    assert report["coverage_floor_enforced"] is False
    assert report["passed"] is True
    activate_policy(
        conn, revised.policy_id, approval_token=approval_token, activated_by=OPERATOR
    )
    assert store.get(conn, revised.policy_id).status == PolicyStatus.ACTIVE


def test_the_waiver_never_covers_false_automatic_actions(conn, candidate):
    """Zero false actions is not waivable, for anyone, ever."""
    _first, teach = candidate
    revised = revise_candidate(
        conn, teach.policy_id, max_cost_usd=5.0, min_confidence=0.75,
        kit_category=None, revised_by=OPERATOR,
    )
    assert revised.replay["false_automatic_actions"] == 0
    assert "false" not in " ".join(revised.replay["blocking_reasons"])


def test_a_widening_revision_still_faces_the_coverage_floor(conn, candidate):
    """The exemption is for narrowing only; loosening is held to the full bar."""
    _first, teach = candidate
    revised = revise_candidate(
        conn, teach.policy_id, max_cost_usd=45.0, min_confidence=0.75,
        kit_category=None, revised_by=OPERATOR,
    )
    assert revised.replay["coverage_floor_enforced"] is True


def test_an_agent_proposal_is_always_held_to_the_coverage_floor(conn):
    """Nothing about the waiver relaxes the gate for a proposal."""
    from app.policy.replay import replay_candidate_policy

    payload = demo_policy_payload()
    payload["conditions"][-1]["value"] = 7.0
    payload["actions"][1]["max_cost_usd"] = 7.0
    report = replay_candidate_policy(conn, validate_policy_payload(payload))
    assert report.coverage_floor_enforced is True
    assert not report.passed
    assert any("coverage" in b for b in report.blocking_reasons)


def test_a_revision_restates_its_own_terms(conn, candidate):
    """A revised policy must not describe a cap it no longer has."""
    _first, teach = candidate
    revised = revise_candidate(
        conn, teach.policy_id, max_cost_usd=12.0, min_confidence=0.85,
        kit_category="camera_kit", revised_by=OPERATOR,
    )
    description = revised.definition.description
    assert "$12.00" in description
    assert "0.85" in description
    assert "camera kits" in description
    assert "$25.00 or less" not in description


def test_repeated_revisions_do_not_stack_description_clauses(conn, candidate):
    _first, teach = candidate
    r1 = revise_candidate(conn, teach.policy_id, max_cost_usd=20.0, min_confidence=0.8,
                          kit_category=None, revised_by=OPERATOR)
    r2 = revise_candidate(conn, r1.policy_id, max_cost_usd=15.0, min_confidence=0.9,
                          kit_category=None, revised_by=OPERATOR)
    assert r2.definition.description.count("Revised by a person") == 1
    assert "$15.00" in r2.definition.description
    assert "$20.00" not in r2.definition.description
    assert len(r2.definition.description) <= 600
