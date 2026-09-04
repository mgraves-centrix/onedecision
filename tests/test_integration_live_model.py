"""Opt-in integration test against a live model provider.

Deselected by default. Everything else in this suite is hermetic: no network,
no credentials, no spend.

Run it deliberately:

    ONEDECISION_MODEL_PROVIDER=bedrock AWS_REGION=us-west-2 \
        pytest -m integration tests/test_integration_live_model.py

or, with an Anthropic API key:

    ONEDECISION_MODEL_PROVIDER=anthropic ANTHROPIC_API_KEY=... \
        pytest -m integration tests/test_integration_live_model.py

It asserts the same contract the offline provider satisfies: a real Strands
agent, real tool calls, typed structured output. If a hosted model returns a
weaker report than the offline provider, that is a finding, not a flake — the
guardrails downstream are identical either way.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.integration

LIVE_PROVIDERS = {"bedrock", "anthropic"}


@pytest.fixture()
def live_settings(monkeypatch):
    provider = os.environ.get("ONEDECISION_MODEL_PROVIDER", "scripted")
    if provider not in LIVE_PROVIDERS:
        pytest.skip(
            "set ONEDECISION_MODEL_PROVIDER=bedrock|anthropic to run the live integration test"
        )
    from app import config

    monkeypatch.setenv("ONEDECISION_MODEL_PROVIDER", provider)
    new_settings = config.reload_settings()

    import app.agent.providers as providers

    monkeypatch.setattr(providers, "default_settings", new_settings, raising=False)
    return new_settings


def test_live_agent_investigates_with_real_tool_calls(conn, live_settings):
    from app.agent.build import investigation_agent
    from app.agent.tools import AgentContext
    from app.domain import InvestigationReport

    ctx = AgentContext(conn=conn, trace_id=f"trc_{uuid.uuid4().hex[:12]}", case_id="CASE-2001")
    agent = investigation_agent(ctx)
    result = agent(
        "Investigate return case CASE-2001 and report what you found.",
        structured_output_model=InvestigationReport,
    )

    report = result.structured_output
    assert isinstance(report, InvestigationReport)
    assert "get_return_case" in ctx.tool_names
    assert "compare_expected_and_received" in ctx.tool_names
    assert report.case_id == "CASE-2001"
    assert report.observed_missing_component_count == 1
    assert report.observed_serial_match is True
    assert report.recommended_action in {"request_decision", "escalate", "apply_policy"}


def test_live_agent_report_reconciles_with_the_source_systems(conn, live_settings):
    """A hosted model must not disagree with the systems on a clean case."""
    from app.agent.build import investigation_agent
    from app.agent.tools import AgentContext
    from app.domain import InvestigationReport
    from app.facts import derive_facts, reconcile

    ctx = AgentContext(conn=conn, trace_id=f"trc_{uuid.uuid4().hex[:12]}", case_id="CASE-2001")
    agent = investigation_agent(ctx)
    result = agent(
        "Investigate return case CASE-2001 and report what you found.",
        structured_output_model=InvestigationReport,
    )
    report = result.structured_output
    assert isinstance(report, InvestigationReport)
    assert reconcile(report, derive_facts(conn, "CASE-2001")) == []


def test_live_agent_proposes_a_schema_valid_policy(conn, live_settings):
    """Whatever a hosted model proposes must survive the allowlist validator."""
    from app.orchestrator import approve_and_teach, handle_event

    first = handle_event("CASE-2001", conn=conn)
    teach = approve_and_teach(conn, first.exception_id, decided_by="integration-test")
    assert teach.definition.family == "returns.missing_accessory"
    assert {a.type for a in teach.definition.actions} == {
        "set_disposition",
        "create_work_order",
        "close_exception",
    }
    assert teach.replay["false_automatic_actions"] == 0
