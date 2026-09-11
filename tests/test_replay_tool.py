"""The policy-proposal agent dry-runs candidates in the same shape it proposes them.

On Bedrock, the replay tool used to take the full stored policy, actions and all,
while the agent's proposal carries only conditions and a spend cap. The model
spent most of a 115K-token proposal step discovering the second schema by trial
and error. The tool now takes the proposal's shape and adds the fixed actions
itself, exactly as the real candidate gets them.
"""

from __future__ import annotations

import json
import uuid

from app.agent.tools import AgentContext, build_tools
from app.facts import derive_facts
from app.orchestrator import _provisional_policy_payload


def _replay_tool(conn):
    ctx = AgentContext(conn=conn, trace_id=f"trc_{uuid.uuid4().hex[:12]}", case_id="CASE-2001")
    tool = next(t for t in build_tools(ctx) if t.tool_name == "replay_candidate_policy")
    return ctx, tool


def _candidate(conn) -> dict:
    return _provisional_policy_payload(derive_facts(conn, "CASE-2001"))


def test_replay_accepts_the_proposal_shape(conn):
    ctx, replay = _replay_tool(conn)
    candidate = _candidate(conn)
    assert "actions" not in candidate  # the scripted candidate has the proposal's shape too

    result = json.loads(replay(policy_json=json.dumps(candidate)))

    assert "error" not in result
    assert result["cases_replayed"] == 24
    assert result["false_automatic_actions"] == 0
    assert ctx.calls[-1].ok


def test_actions_sent_by_the_model_are_ignored_not_trusted(conn):
    ctx, replay = _replay_tool(conn)
    candidate = _candidate(conn) | {
        "family": "something.else",
        "actions": [{"type": "create_work_order", "work_order_type": "REPLACEMENT_PARTS", "max_cost_usd": 5000}],
    }

    result = json.loads(replay(policy_json=json.dumps(candidate)))

    assert result["ignored_fields"] == ["actions", "family"]
    assert result["false_automatic_actions"] == 0
    assert ctx.calls[-1].ok


def test_a_malformed_candidate_says_what_the_tool_expects(conn):
    ctx, replay = _replay_tool(conn)
    candidate = _candidate(conn)
    del candidate["max_cost_usd"]

    result = json.loads(replay(policy_json=json.dumps(candidate)))

    assert result["error"] == "candidate failed validation"
    assert any(d.startswith("max_cost_usd") for d in result["details"])
    assert "max_cost_usd" in result["expected_fields"]
    assert not ctx.calls[-1].ok
