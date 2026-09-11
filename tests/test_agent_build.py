"""How the agent runs its tools.

A live run against Bedrock had the model request three tool calls in one turn.
Strands runs those concurrently by default, every tool shares one database
connection, and the concurrent queries read back each other's rows: the case
lookup failed and CASE-2001 was reported as missing. The agent escalated, which
was safe, but it never saw the facts. Tools must run one at a time.
"""

from __future__ import annotations

import uuid

import pytest
from strands.tools.executors import SequentialToolExecutor

from app.agent.build import decision_card_agent, investigation_agent, policy_proposal_agent
from app.agent.tools import AgentContext


@pytest.mark.parametrize(
    "factory", [investigation_agent, decision_card_agent, policy_proposal_agent]
)
def test_every_agent_runs_its_tools_one_at_a_time(conn, factory):
    ctx = AgentContext(conn=conn, trace_id=f"trc_{uuid.uuid4().hex[:12]}", case_id="CASE-2001")

    agent = factory(ctx)

    assert isinstance(agent.tool_executor, SequentialToolExecutor)
