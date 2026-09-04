"""The policy language is an allowlist. These tests are the wall."""

from __future__ import annotations

import pytest

from app.policy.schema import (
    ALLOWED_FIELDS,
    PolicyValidationError,
    validate_policy_payload,
)
from tests.conftest import demo_policy_payload


def test_valid_policy_parses():
    policy = validate_policy_payload(demo_policy_payload())
    assert policy.family == "returns.missing_accessory"
    assert len(policy.conditions) == 8
    assert {a.type for a in policy.actions} == {
        "set_disposition",
        "create_work_order",
        "close_exception",
    }


@pytest.mark.parametrize(
    "field",
    ["inspector_notes", "customer_ref", "declared_value_usd", "__class__", "os.system"],
)
def test_off_allowlist_field_rejected(field):
    payload = demo_policy_payload()
    payload["conditions"][0] = {"field": field, "operator": "eq", "value": 1}
    with pytest.raises(PolicyValidationError):
        validate_policy_payload(payload)
    assert field not in ALLOWED_FIELDS


@pytest.mark.parametrize("operator", ["regex", "matches", "like", "call", "exec", "contains"])
def test_off_allowlist_operator_rejected(operator):
    payload = demo_policy_payload()
    payload["conditions"][0] = {
        "field": "missing_component_count",
        "operator": operator,
        "value": 1,
    }
    with pytest.raises(PolicyValidationError):
        validate_policy_payload(payload)


@pytest.mark.parametrize(
    "action",
    [
        {"type": "issue_refund", "amount_usd": 500},
        {"type": "send_email", "to": "someone@example.com"},
        {"type": "set_disposition", "disposition": "RESTOCK_SELLABLE"},
        {"type": "create_work_order", "work_order_type": "SCRAP_UNIT", "max_cost_usd": 10},
        {"type": "run_script", "code": "import os; os.system('id')"},
    ],
)
def test_off_allowlist_action_rejected(action):
    payload = demo_policy_payload()
    payload["actions"] = [action]
    with pytest.raises(PolicyValidationError):
        validate_policy_payload(payload)


def test_natural_language_condition_rejected():
    payload = demo_policy_payload()
    payload["conditions"][0] = {
        "field": "missing_component_count",
        "operator": "eq",
        "value": "if the item seems cheap and the customer is nice",
    }
    with pytest.raises(PolicyValidationError):
        validate_policy_payload(payload)


def test_cost_threshold_above_hard_ceiling_rejected():
    payload = demo_policy_payload()
    payload["conditions"][-1]["value"] = 5000.0
    payload["actions"][1]["max_cost_usd"] = 5000.0
    with pytest.raises(PolicyValidationError) as exc:
        validate_policy_payload(payload)
    assert any("ceiling" in e for e in exc.value.errors)


def test_spend_cap_may_not_exceed_its_own_cost_condition():
    payload = demo_policy_payload()
    payload["actions"][1]["max_cost_usd"] = 49.0  # under the ceiling, over the condition
    with pytest.raises(PolicyValidationError) as exc:
        validate_policy_payload(payload)
    assert any("exceeds the policy's own" in e for e in exc.value.errors)


def test_work_order_requires_a_cost_bound():
    payload = demo_policy_payload()
    payload["conditions"] = [c for c in payload["conditions"] if c["field"] != "replacement_cost_usd"]
    with pytest.raises(PolicyValidationError) as exc:
        validate_policy_payload(payload)
    assert any("bound replacement_cost_usd" in e for e in exc.value.errors)


def test_acting_policy_must_also_dispose_and_close():
    payload = demo_policy_payload()
    payload["actions"] = [payload["actions"][1]]
    with pytest.raises(PolicyValidationError):
        validate_policy_payload(payload)


def test_boolean_field_rejects_numeric_value():
    payload = demo_policy_payload()
    payload["conditions"][1]["value"] = 1
    with pytest.raises(PolicyValidationError):
        validate_policy_payload(payload)


def test_extra_keys_are_forbidden():
    payload = demo_policy_payload()
    payload["conditions"][0]["shell"] = "rm -rf /"
    with pytest.raises(PolicyValidationError):
        validate_policy_payload(payload)


def test_duplicate_field_conditions_rejected():
    payload = demo_policy_payload()
    payload["conditions"].append(
        {"field": "serial_match", "operator": "eq", "value": False}
    )
    with pytest.raises(PolicyValidationError):
        validate_policy_payload(payload)
