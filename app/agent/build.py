"""Construct the one OneDecision Strands agent.

There is exactly one agent. It is invoked three times along the golden path —
investigate, produce a decision card, propose a policy — with the same tools and
a task-specific system prompt each time. Extra agents would add moving parts
without adding capability.
"""

from __future__ import annotations

from typing import Any

from strands import Agent

from app.agent import prompts
from app.agent.providers import resolve_model
from app.agent.tools import AgentContext, build_tools

AGENT_NAME = "onedecision-returns-agent"


def build_agent(
    ctx: AgentContext,
    *,
    system_prompt: str,
    model: Any | None = None,
    tools: list[Any] | None = None,
) -> Agent:
    return Agent(
        model=model or resolve_model(),
        tools=tools if tools is not None else build_tools(ctx),
        system_prompt=system_prompt,
        name=AGENT_NAME,
        callback_handler=None,
    )


def investigation_agent(ctx: AgentContext, *, model: Any | None = None) -> Agent:
    all_tools = build_tools(ctx)
    read_only = [t for t in all_tools if t.tool_name != "replay_candidate_policy"]
    return build_agent(ctx, system_prompt=prompts.INVESTIGATION_PROMPT, model=model, tools=read_only)


def decision_card_agent(ctx: AgentContext, *, model: Any | None = None) -> Agent:
    return build_agent(ctx, system_prompt=prompts.DECISION_CARD_PROMPT, model=model, tools=[])


def policy_proposal_agent(ctx: AgentContext, *, model: Any | None = None) -> Agent:
    all_tools = build_tools(ctx)
    replay_only = [t for t in all_tools if t.tool_name == "replay_candidate_policy"]
    return build_agent(
        ctx, system_prompt=prompts.POLICY_PROPOSAL_PROMPT, model=model, tools=replay_only
    )
