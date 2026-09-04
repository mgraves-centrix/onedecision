"""Guardrails outrank policies. A policy can narrow automation, never widen it."""

from __future__ import annotations

import pytest

from app.domain import CaseFacts, MissingComponent
from app.policy.guardrails import evaluate_guardrails


def facts(**overrides) -> CaseFacts:
    base = dict(
        case_id="CASE-TEST",
        sku="NGO-KIT-4100",
        kit_category="camera_kit",
        missing_component_count=1,
        missing_component_serialized=False,
        missing_component_safety_critical=False,
        missing_component_essential=False,
        serial_match=True,
        replacement_cost_usd=14.0,
        new_damage_present=False,
        evidence_complete=True,
        missing_components=(
            MissingComponent(
                component_id="CMP-STRAP-NEO",
                name="Neoprene shoulder strap",
                serialized=False,
                safety_critical=False,
                essential=False,
                replacement_cost_usd=14.0,
            ),
        ),
    )
    base.update(overrides)
    return CaseFacts(**base)


def test_clean_case_passes():
    assert evaluate_guardrails(facts(), confidence=0.9).passed


@pytest.mark.parametrize(
    "override,fragment",
    [
        ({"serial_match": False}, "serial number does not match"),
        ({"new_damage_present": True}, "new damage"),
        ({"evidence_complete": False}, "evidence is incomplete"),
        ({"replacement_cost_usd": None}, "replacement cost is unavailable"),
        ({"replacement_cost_usd": 999.0}, "exceeds the hard ceiling"),
        ({"missing_component_count": 0}, "no missing component"),
        ({"missing_component_count": 3}, "hard ceiling"),
        ({"missing_component_serialized": True}, "serialized"),
        ({"missing_component_safety_critical": True}, "safety-critical"),
        ({"missing_component_essential": True}, "essential"),
    ],
)
def test_each_invariant_blocks(override, fragment):
    result = evaluate_guardrails(facts(**override), confidence=0.9)
    assert result.blocked
    assert any(fragment in r for r in result.reasons), result.reasons


def test_low_confidence_blocks():
    result = evaluate_guardrails(facts(), confidence=0.4)
    assert result.blocked
    assert any("confidence" in r for r in result.reasons)


def test_tool_failure_blocks():
    result = evaluate_guardrails(facts(), confidence=0.9, tool_failures=("parts catalog down",))
    assert result.blocked
    assert any("tool failure" in r for r in result.reasons)


def test_conflicting_policies_block():
    result = evaluate_guardrails(facts(), confidence=0.9, matching_policy_count=2)
    assert result.blocked
    assert any("conflict" in r for r in result.reasons)


def test_threshold_boundaries():
    from app.config import MAX_REPLACEMENT_COST_CEILING_USD as ceiling

    assert evaluate_guardrails(facts(replacement_cost_usd=ceiling), confidence=0.9).passed
    assert evaluate_guardrails(facts(replacement_cost_usd=ceiling + 0.01), confidence=0.9).blocked


def test_confidence_threshold_boundary():
    from app.config import settings

    t = settings.confidence_threshold
    assert evaluate_guardrails(facts(), confidence=t).passed
    assert evaluate_guardrails(facts(), confidence=t - 0.001).blocked
