"""The activation gate. Nothing acts until a human says so."""

from __future__ import annotations

import pytest

from app.domain import PolicyStatus
from app.policy import store
from app.policy.replay import replay_candidate_policy
from app.policy.schema import PolicyValidationError
from tests.conftest import demo_policy_payload


def make_candidate(conn, **overrides):
    return store.create_candidate(
        conn, payload=demo_policy_payload(**overrides), trace_id="trc_test"
    )


def test_a_proposal_starts_inert(conn):
    record = make_candidate(conn)
    assert record.status == PolicyStatus.CANDIDATE
    assert store.list_active(conn) == []


def test_activation_without_replay_is_denied(conn, approval_token):
    record = make_candidate(conn)
    with pytest.raises(store.ActivationDenied) as exc:
        store.activate(
            conn, record.policy_id, approval_token=approval_token,
            activated_by="dana", trace_id="trc_test",
        )
    assert "replay" in str(exc.value)
    assert store.get(conn, record.policy_id).status == PolicyStatus.CANDIDATE


def test_activation_with_a_failing_replay_is_denied(conn, approval_token):
    payload = demo_policy_payload()
    payload["conditions"][-1]["value"] = 0.01
    payload["actions"][1]["max_cost_usd"] = 0.01
    record = store.create_candidate(conn, payload=payload, trace_id="trc_test")
    report = replay_candidate_policy(conn, record.definition)
    assert not report.passed
    store.attach_replay_report(conn, record.policy_id, report.to_dict(), trace_id="trc_test")

    with pytest.raises(store.ActivationDenied) as exc:
        store.activate(
            conn, record.policy_id, approval_token=approval_token,
            activated_by="dana", trace_id="trc_test",
        )
    assert "replay did not pass" in str(exc.value)


def test_activation_without_a_token_is_denied(conn):
    record = make_candidate(conn)
    report = replay_candidate_policy(conn, record.definition)
    store.attach_replay_report(conn, record.policy_id, report.to_dict(), trace_id="trc_test")
    for bad in ("", "guess", "replace-me-local-demo-token"):
        with pytest.raises(store.ActivationDenied) as exc:
            store.activate(
                conn, record.policy_id, approval_token=bad,
                activated_by="dana", trace_id="trc_test",
            )
        assert "approval token" in str(exc.value)


def test_activation_succeeds_after_a_passing_replay(conn, approval_token):
    record = make_candidate(conn)
    report = replay_candidate_policy(conn, record.definition)
    store.attach_replay_report(conn, record.policy_id, report.to_dict(), trace_id="trc_test")
    activated = store.activate(
        conn, record.policy_id, approval_token=approval_token,
        activated_by="dana", trace_id="trc_test",
    )
    assert activated.status == PolicyStatus.ACTIVE
    assert activated.activated_by == "dana"
    assert [p.policy_id for p in store.list_active(conn)] == [record.policy_id]


def test_activating_twice_is_denied(conn, approval_token):
    record = make_candidate(conn)
    report = replay_candidate_policy(conn, record.definition)
    store.attach_replay_report(conn, record.policy_id, report.to_dict(), trace_id="trc_test")
    store.activate(conn, record.policy_id, approval_token=approval_token,
                   activated_by="dana", trace_id="trc_test")
    with pytest.raises(store.ActivationDenied) as exc:
        store.activate(conn, record.policy_id, approval_token=approval_token,
                       activated_by="dana", trace_id="trc_test")
    assert "only a candidate may be activated" in str(exc.value)


def test_a_new_version_supersedes_the_old_one(conn, approval_token):
    first = make_candidate(conn)
    store.attach_replay_report(
        conn, first.policy_id, replay_candidate_policy(conn, first.definition).to_dict(),
        trace_id="trc_test",
    )
    store.activate(conn, first.policy_id, approval_token=approval_token,
                   activated_by="dana", trace_id="trc_test")

    second = make_candidate(conn, name="Single low-cost accessory replacement v2")
    store.attach_replay_report(
        conn, second.policy_id, replay_candidate_policy(conn, second.definition).to_dict(),
        trace_id="trc_test",
    )
    store.activate(conn, second.policy_id, approval_token=approval_token,
                   activated_by="dana", trace_id="trc_test")

    active = store.list_active(conn)
    assert [p.policy_id for p in active] == [second.policy_id]
    assert store.get(conn, first.policy_id).status == PolicyStatus.RETIRED
    assert second.version == first.version + 1


def test_an_invalid_proposal_never_becomes_a_candidate(conn):
    payload = demo_policy_payload()
    payload["actions"] = [{"type": "issue_refund", "amount_usd": 9999}]
    with pytest.raises(PolicyValidationError):
        store.create_candidate(conn, payload=payload, trace_id="trc_test")
    assert store.list_all(conn) == []
