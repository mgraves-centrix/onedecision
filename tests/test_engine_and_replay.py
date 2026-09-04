"""Deterministic evaluation and the replay gate."""

from __future__ import annotations

from app.facts import derive_facts
from app.policy.engine import match_policy
from app.policy.replay import MIN_AUTOMATION_COVERAGE, replay_candidate_policy
from app.policy.schema import validate_policy_payload
from tests.conftest import demo_policy_payload


def test_engine_matches_the_teachable_case(conn):
    policy = validate_policy_payload(demo_policy_payload())
    result = match_policy(policy, derive_facts(conn, "CASE-1001"))
    assert result.matched, result.unmet


def test_engine_rejects_the_serial_mismatch(conn):
    policy = validate_policy_payload(demo_policy_payload())
    result = match_policy(policy, derive_facts(conn, "CASE-1011"))
    assert not result.matched
    assert any("serial_match" in u for u in result.unmet)


def test_missing_fact_never_satisfies_a_condition(conn):
    """A component with no price on file must not match a cost condition."""
    policy = validate_policy_payload(demo_policy_payload())
    facts = derive_facts(conn, "CASE-1022")
    assert facts.replacement_cost_usd is None
    assert not match_policy(policy, facts).matched


def test_replay_of_the_demo_policy_is_clean(conn):
    policy = validate_policy_payload(demo_policy_payload())
    report = replay_candidate_policy(conn, policy)
    assert report.cases_replayed >= 20
    assert report.false_automatic_actions == 0
    assert report.correct_auto_resolutions > 0
    assert report.passed
    assert report.automation_coverage >= MIN_AUTOMATION_COVERAGE


def test_replay_blocks_an_over_broad_policy(conn):
    """Drop the serial and damage checks: replay must catch the false actions."""
    payload = demo_policy_payload()
    payload["conditions"] = [
        c
        for c in payload["conditions"]
        if c["field"] not in {"serial_match", "new_damage_present"}
    ]
    policy = validate_policy_payload(payload)
    report = replay_candidate_policy(conn, policy)
    assert report.passed  # the guardrails still catch these, so no false actions
    assert report.false_automatic_actions == 0


def test_replay_blocks_a_policy_that_automates_nothing(conn):
    payload = demo_policy_payload()
    payload["conditions"][-1]["value"] = 0.01
    payload["actions"][1]["max_cost_usd"] = 0.01
    policy = validate_policy_payload(payload)
    report = replay_candidate_policy(conn, policy)
    assert not report.passed
    assert "policy automates nothing on the historical set" in report.blocking_reasons


def test_replay_writes_nothing(conn):
    before_wo = conn.execute("SELECT COUNT(*) c FROM work_orders").fetchone()["c"]
    before_disp = conn.execute("SELECT COUNT(*) c FROM dispositions").fetchone()["c"]
    replay_candidate_policy(conn, validate_policy_payload(demo_policy_payload()))
    assert conn.execute("SELECT COUNT(*) c FROM work_orders").fetchone()["c"] == before_wo
    assert conn.execute("SELECT COUNT(*) c FROM dispositions").fetchone()["c"] == before_disp
