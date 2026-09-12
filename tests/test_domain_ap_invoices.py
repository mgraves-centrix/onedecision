"""A second domain, on exactly the same machinery.

Accounts payable has nothing to do with camera kits: different facts, different
guardrails, different systems of record, different actions. What it shares is
every guarantee — the constrained policy language, the replay gate, the
activation gate, idempotent execution, read-back verification, and the audit log.

These tests are the claim's evidence. None of them touch returns, and none of
them needed a change to the governance code to pass.
"""

from __future__ import annotations

import uuid

import pytest

from app import audit, config, domains
from app.audit import AuditEventType
from app.domain import ExceptionStatus
from app.domains import ap_invoices as ap
from app.orchestrator import execute_approved_policy, idempotency_key, verify_action
from app.policy import store as policy_store
from app.policy.engine import match_policy
from app.policy.replay import replay_candidate_policy
from app.policy.schema import PolicyValidationError, validate_policy_payload
from app.policy.store import ActivationDenied

def token() -> str:
    """The approval token this environment is configured with, read when it is
    used: the test fixtures override it per run."""
    return config.settings.approval_token


def candidate_payload(**over) -> dict:
    """The policy an AP clerk would teach: small, clean variances on a matched PO."""
    payload = {
        "family": ap.FAMILY,
        "name": "Small clean price variance on a matched purchase order",
        "description": (
            "Variance under $75 and under 2%, with the purchase order, the receipt and "
            "the tax all reconciling, and no duplicate or held vendor."
        ),
        "conditions": [
            {"field": "variance_usd", "operator": "lte", "value": 75},
            {"field": "variance_pct", "operator": "lte", "value": 2},
            {"field": "po_match", "operator": "eq", "value": True},
            {"field": "receipt_match", "operator": "eq", "value": True},
            {"field": "tax_consistent", "operator": "eq", "value": True},
            {"field": "duplicate_suspected", "operator": "eq", "value": False},
            {"field": "vendor_on_hold", "operator": "eq", "value": False},
        ],
        "actions": ap.fixed_actions(75.0),
        "min_confidence": 0.75,
    }
    payload.update(over)
    return payload


def open_exception(conn, invoice_id: str) -> tuple[str, str]:
    """An exception row for an invoice, which is what the machinery governs."""
    exception_id = f"exc_{uuid.uuid4().hex[:12]}"
    trace_id = f"trc_{uuid.uuid4().hex[:12]}"
    now = "2026-09-11T00:00:00.000+00:00"
    conn.execute(
        """INSERT INTO exceptions (exception_id, case_id, family, trace_id, status,
               event_key, summary, escalation_reasons, applied_policy_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            exception_id,
            invoice_id,
            ap.FAMILY,
            trace_id,
            ExceptionStatus.INVESTIGATING,
            f"ap:{invoice_id}:{uuid.uuid4().hex[:6]}",
            "",
            "[]",
            None,
            now,
            now,
        ),
    )
    return exception_id, trace_id


def activated_policy(conn) -> str:
    record = policy_store.create_candidate(
        conn, payload=candidate_payload(), trace_id="trc_ap_test", origin_case_id="AP-2001"
    )
    report = replay_candidate_policy(conn, record.definition)
    policy_store.attach_replay_report(
        conn, record.policy_id, report.to_dict(), trace_id="trc_ap_test"
    )
    policy_store.activate(
        conn,
        record.policy_id,
        approval_token=token(),
        activated_by="ap.clerk@northgate-optics.example",
        trace_id="trc_ap_test",
    )
    return record.policy_id


# ----------------------------------------------------------------- the pack


def test_the_domain_is_registered_with_its_own_fields_and_actions():
    domains.load()

    spec = domains.get(ap.FAMILY)

    assert "variance_usd" in spec.allowed_fields
    assert "replacement_cost_usd" not in spec.allowed_fields  # that belongs to returns
    assert [a.type for a in spec.actions] == ["post_adjustment", "release_payment", "close_exception"]


def test_facts_are_derived_from_the_ledger_not_from_a_model(conn):
    facts = ap.derive_facts(conn, "AP-2001")

    assert facts.variance_usd == 41.50
    assert facts.po_match and facts.receipt_match and facts.tax_consistent
    assert not facts.duplicate_suspected and not facts.vendor_on_hold
    assert facts.vendor_risk_tier == "low"
    assert set(facts.policy_view()) == set(ap.BOOL_FIELDS | ap.NUMBER_FIELDS | set(ap.ENUM_FIELDS))


@pytest.mark.parametrize(
    "invoice_id, reason",
    [
        ("AP-1013", "duplicate"),
        ("AP-1015", "payment hold"),
        ("AP-1016", "no purchase order"),
        ("AP-1017", "goods received"),
        ("AP-1018", "tax"),
        ("AP-1019", "hard ceiling"),
        ("AP-1021", "evidence is incomplete"),
    ],
)
def test_every_boundary_blocks_before_any_policy_is_consulted(conn, invoice_id, reason):
    facts = ap.derive_facts(conn, invoice_id)

    result = ap.evaluate_guardrails(facts, confidence=0.99)

    assert result.blocked
    assert any(reason in r for r in result.reasons), result.reasons


# ------------------------------------------------------- the policy language


def test_the_language_refuses_what_this_domain_cannot_express(conn):
    with pytest.raises(PolicyValidationError) as exc:
        validate_policy_payload(
            candidate_payload(
                conditions=[{"field": "replacement_cost_usd", "operator": "lte", "value": 20}]
            )
        )

    assert "does not belong to family" in " ".join(exc.value.errors)


def test_an_adjustment_may_not_exceed_the_condition_it_was_replayed_under(conn):
    over_cap = ap.fixed_actions(75.0)
    over_cap[0] = {**over_cap[0], "max_amount_usd": 200.0}

    with pytest.raises(PolicyValidationError) as exc:
        validate_policy_payload(candidate_payload(actions=over_cap))

    assert "exceeds the policy's own variance_usd bound" in " ".join(exc.value.errors)


# ------------------------------------------------------------- the gates


def test_replay_runs_the_candidate_against_the_labeled_invoice_history(conn):
    definition = validate_policy_payload(candidate_payload())

    report = replay_candidate_policy(conn, definition)

    assert report.cases_replayed == 24
    assert report.false_automatic_actions == 0
    assert report.correct_auto_resolutions == 12
    assert report.correct_escalations == 12
    assert report.passed


def test_a_policy_that_would_pay_a_duplicate_cannot_be_activated(conn):
    # Drop the duplicate guard from the conditions: the guardrail still catches the
    # duplicates, so what this proves is that replay scores the candidate honestly.
    loose = candidate_payload(
        conditions=[
            {"field": "variance_usd", "operator": "lte", "value": 250},
            {"field": "variance_pct", "operator": "lte", "value": 5},
        ],
        actions=ap.fixed_actions(250.0),
    )
    record = policy_store.create_candidate(
        conn, payload=loose, trace_id="trc_ap_loose", origin_case_id="AP-2001"
    )
    report = replay_candidate_policy(conn, record.definition)
    policy_store.attach_replay_report(
        conn, record.policy_id, report.to_dict(), trace_id="trc_ap_loose"
    )

    with pytest.raises(ActivationDenied):
        policy_store.activate(
            conn,
            record.policy_id,
            approval_token=token(),
            activated_by="ap.clerk@northgate-optics.example",
            trace_id="trc_ap_loose",
        )


def test_activation_still_needs_a_human_token(conn):
    record = policy_store.create_candidate(
        conn, payload=candidate_payload(), trace_id="trc_ap_token", origin_case_id="AP-2001"
    )
    report = replay_candidate_policy(conn, record.definition)
    policy_store.attach_replay_report(
        conn, record.policy_id, report.to_dict(), trace_id="trc_ap_token"
    )

    with pytest.raises(ActivationDenied):
        policy_store.activate(
            conn,
            record.policy_id,
            approval_token="",
            activated_by="ap.clerk@northgate-optics.example",
            trace_id="trc_ap_token",
        )


# --------------------------------------------------------- act and verify


def test_a_matching_invoice_is_paid_out_and_read_back(conn):
    policy_id = activated_policy(conn)
    facts = ap.derive_facts(conn, "AP-2002")
    exception_id, trace_id = open_exception(conn, "AP-2002")
    assert match_policy(policy_store.get(conn, policy_id).definition, facts).matched

    results = execute_approved_policy(
        conn,
        "AP-2002",
        policy_id,
        idempotency_key("AP-2002", policy_id),
        trace_id=trace_id,
        exception_id=exception_id,
        facts=facts,
    )
    verification = verify_action(
        conn, "AP-2002", policy_id, trace_id=trace_id, exception_id=exception_id
    )

    assert [r.ok for r in results] == [True, True, True]
    assert verification.ok, verification.failures
    assert any("adjustment on file" in c for c in verification.checks)
    assert any("released for payment" in c for c in verification.checks)


def test_running_it_twice_pays_once(conn):
    policy_id = activated_policy(conn)
    facts = ap.derive_facts(conn, "AP-2002")
    exception_id, trace_id = open_exception(conn, "AP-2002")
    key = idempotency_key("AP-2002", policy_id)

    first = execute_approved_policy(
        conn, "AP-2002", policy_id, key, trace_id=trace_id, exception_id=exception_id, facts=facts
    )
    second = execute_approved_policy(
        conn, "AP-2002", policy_id, key, trace_id=trace_id, exception_id=exception_id, facts=facts
    )

    assert not any(r.duplicate_suppressed for r in first[:2])
    assert all(r.duplicate_suppressed for r in second[:2])
    assert len(ap.ap_ledger.get_adjustments(conn, "AP-2002")) == 1


def test_every_action_lands_in_the_same_hash_chained_log(conn):
    policy_id = activated_policy(conn)
    facts = ap.derive_facts(conn, "AP-2002")
    exception_id, trace_id = open_exception(conn, "AP-2002")

    execute_approved_policy(
        conn,
        "AP-2002",
        policy_id,
        idempotency_key("AP-2002", policy_id),
        trace_id=trace_id,
        exception_id=exception_id,
        facts=facts,
    )
    verify_action(conn, "AP-2002", policy_id, trace_id=trace_id, exception_id=exception_id)

    events = [e.event_type for e in audit.read_for_case(conn, "AP-2002")]
    assert events.count(AuditEventType.ACTION_EXECUTED) == 3
    assert AuditEventType.VERIFICATION_PASSED in events
    assert audit.verify_chain(conn).ok
