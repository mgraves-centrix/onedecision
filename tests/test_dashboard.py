"""The operations dashboard: history and usage, counted from the product's own records."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import audit
from app.audit import AuditEventType
from app.dashboard import build_dashboard, compact
from app.orchestrator import handle_event

TOOLS = {
    "get_return_case",
    "compare_expected_and_received",
    "lookup_replacement_cost",
    "find_approved_policy",
}


@pytest.fixture()
def client(temp_db):
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_the_dashboard_renders_before_anything_has_happened(client):
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "<h1>Dashboard</h1>" in r.text
    assert "No cases in this range yet." in r.text
    assert "No agent runs yet" in r.text


def test_every_agent_run_is_recorded_for_the_usage_view(conn):
    handle_event("CASE-2001", conn=conn)

    runs = [e for e in audit.read_for_case(conn, "CASE-2001") if e.event_type == "agent.run"]

    assert [r.payload["step"] for r in runs] == ["investigation", "decision_card"]
    assert runs[0].payload["tool_calls"] == 4
    assert all(r.payload["duration_ms"] >= 0 for r in runs)


def test_a_handled_case_shows_up_in_history_and_usage(conn):
    handle_event("CASE-2001", conn=conn)

    d = build_dashboard(conn)

    assert d["cases"]["total"] == 1
    assert d["cases"]["waiting"] == 1
    assert d["usage"]["agent_runs"] == 2
    assert d["usage"]["tool_calls"] == 4
    assert {t["name"] for t in d["usage"]["tools"]} == TOOLS
    # The offline model reports no tokens, and the dashboard must not invent any.
    assert d["usage"]["tokens_reported"] is False


def test_token_usage_is_summed_from_what_the_provider_reported(conn):
    for tokens in (1200, 800):
        audit.record(
            conn,
            trace_id="trc_usage",
            event_type=AuditEventType.AGENT_RUN,
            actor="agent",
            case_id="CASE-2001",
            payload={
                "step": "investigation",
                "provider": "bedrock · us.anthropic.claude-opus-5",
                "input_tokens": tokens,
                "output_tokens": 100,
                "total_tokens": tokens + 100,
                "model_latency_ms": 900,
                "duration_ms": 1500,
                "cycles": 3,
                "tool_calls": 4,
            },
        )

    d = build_dashboard(conn)

    assert d["usage"]["tokens_reported"] is True
    assert d["usage"]["tokens"]["input"] == 2000
    assert d["usage"]["tokens"]["total"] == 2200


def test_the_range_filter_scopes_every_number(conn):
    handle_event("CASE-2001", conn=conn)
    three_days_later = datetime.now(timezone.utc) + timedelta(days=3)

    d = build_dashboard(conn, "24h", now=three_days_later)

    assert d["cases"]["total"] == 0
    assert d["usage"]["agent_runs"] == 0
    assert d["usage"]["tool_calls"] == 0
    assert d["recent_events"] == []


def test_the_activity_chart_puts_todays_case_in_the_last_column(conn):
    handle_event("CASE-2001", conn=conn)

    counts = [c["count"] for c in build_dashboard(conn, "7d")["activity"]["columns"]]

    assert len(counts) == 7
    assert counts[-1] == 1
    assert sum(counts) == 1


def test_an_unknown_range_falls_back_to_all_time(client):
    r = client.get("/dashboard?range=forever")
    assert r.status_code == 200
    assert 'aria-pressed="true">All time</button>' in r.text


def test_the_dashboard_shows_a_handled_case(client):
    client.post("/events/CASE-2001")

    r = client.get("/dashboard")

    assert r.status_code == 200
    assert "CASE-2001" in r.text
    assert "get_return_case" in r.text
    assert "Not reported" in r.text


def test_compact_numbers():
    assert compact(1284) == "1,284"
    assert compact(12_900) == "12.9K"
    assert compact(4_200_000) == "4.2M"
