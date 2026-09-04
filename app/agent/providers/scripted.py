"""A deterministic Strands model provider.

This is a real implementation of the Strands `Model` interface. The Strands
`Agent`, its event loop, its tool registry, its tool execution, and its
structured-output machinery all run exactly as they do against a hosted model —
only the token source is deterministic.

Why it exists:
  * unit tests and CI must be hermetic (no network, no credentials, no spend),
  * the demo must run for a judge with no AWS account,
  * the AWS credentials available while this project was built are not valid
    for Bedrock (see docs/provenance.md).

What it is not: it is not a shortcut around the safety architecture. It emits
proposals like any other model, and every proposal goes through the same
schema validation, guardrails, replay, and human activation gate.
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator, AsyncIterable, Optional, TypeVar

from pydantic import BaseModel
from strands.models.model import Model
from strands.types.content import Message
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolSpec

T = TypeVar("T", bound=BaseModel)

# Fixed order the scripted planner works through during an investigation.
INVESTIGATION_PLAN = (
    "get_return_case",
    "compare_expected_and_received",
    "lookup_replacement_cost",
    "find_approved_policy",
)

PROPOSAL_PLAN = ("replay_candidate_policy",)

HIGH_CONFIDENCE = 0.93
REDUCED_CONFIDENCE = 0.62
LOW_CONFIDENCE = 0.35


class ScriptedModel(Model):
    """Deterministic planner over the OneDecision tool set."""

    def __init__(self, **config: Any) -> None:
        self._config: dict[str, Any] = {"model_id": "scripted-deterministic-v1", **config}

    # ------------------------------------------------------------- Model API
    def get_config(self) -> dict[str, Any]:
        return self._config

    def update_config(self, **model_config: Any) -> None:
        self._config.update(model_config)

    async def stream(
        self,
        messages: list[Message],
        tool_specs: Optional[list[ToolSpec]] = None,
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncIterable[StreamEvent]:
        specs = {s["name"] for s in (tool_specs or [])}
        called = _tools_already_called(messages)
        observations = _collect_observations(messages)

        plan = [name for name in INVESTIGATION_PLAN if name in specs]
        plan += [name for name in PROPOSAL_PLAN if name in specs]

        for tool_name in plan:
            if tool_name in called:
                continue
            payload = _tool_input(tool_name, observations)
            if payload is None:
                continue
            for event in _tool_use_events(tool_name, payload, index=len(called)):
                yield event
            return

        structured = _structured_tool_name(specs)
        if structured and structured not in called:
            payload = build_structured_payload(structured, observations)
            if payload is not None:
                for event in _tool_use_events(structured, payload, index=len(called)):
                    yield event
                return

        yield {"messageStart": {"role": "assistant"}}
        yield {
            "contentBlockDelta": {
                "contentBlockIndex": 0,
                "delta": {"text": _closing_text(observations)},
            }
        }
        yield {"contentBlockStop": {"contentBlockIndex": 0}}
        yield {"messageStop": {"stopReason": "end_turn"}}

    async def structured_output(
        self,
        output_model: type[T],
        prompt: list[Message],
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        observations = _collect_observations(prompt)
        payload = build_structured_payload(output_model.__name__, observations)
        if payload is None:
            raise ValueError(
                f"scripted provider has no builder for output model '{output_model.__name__}'"
            )
        yield {"output": output_model(**payload)}


# --------------------------------------------------------------- transcript


def _tools_already_called(messages: list[Message]) -> list[str]:
    called: list[str] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for block in message.get("content", []) or []:
            use = block.get("toolUse") if isinstance(block, dict) else None
            if use:
                called.append(use["name"])
    return called


def _collect_observations(messages: list[Message]) -> dict[str, Any]:
    """Recover every tool result from the transcript, keyed by tool name."""
    pending: dict[str, str] = {}
    results: dict[str, Any] = {}
    for message in messages:
        for block in message.get("content", []) or []:
            if not isinstance(block, dict):
                continue
            use = block.get("toolUse")
            if use:
                pending[use["toolUseId"]] = use["name"]
            result = block.get("toolResult")
            if result:
                name = pending.get(result.get("toolUseId", ""), "")
                parsed = _parse_tool_result(result)
                if name and parsed is not None:
                    results.setdefault(name, parsed)
    return results


def _parse_tool_result(result: dict[str, Any]) -> Any:
    for block in result.get("content", []) or []:
        text = block.get("text") if isinstance(block, dict) else None
        if not text:
            continue
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            return {"text": text}
    return None


def _structured_tool_name(specs: set[str]) -> str | None:
    known = {"InvestigationReport", "DecisionCard", "PolicyProposal"}
    for name in specs:
        if name in known:
            return name
    return None


# ------------------------------------------------------------- tool inputs


def _tool_input(tool_name: str, observations: dict[str, Any]) -> dict[str, Any] | None:
    case = observations.get("get_return_case") or {}
    comparison = observations.get("compare_expected_and_received") or {}
    case_id = case.get("case_id") or comparison.get("case_id") or _CURRENT_CASE.get("case_id")

    match tool_name:
        case "get_return_case":
            return {"case_id": case_id} if case_id else None
        case "compare_expected_and_received":
            return {"case_id": case_id} if case_id else None
        case "lookup_replacement_cost":
            missing = comparison.get("missing_components") or []
            if not missing:
                return None
            return {"component_id": missing[0]["component_id"]}
        case "find_approved_policy":
            return {"case_id": case_id} if case_id else None
        case "replay_candidate_policy":
            proposal = _CURRENT_CASE.get("candidate_policy")
            return {"policy_json": json.dumps(proposal)} if proposal else None
    return None


# The scripted provider needs a case id before any tool result exists. The
# orchestrator sets this immediately before invoking the agent. A hosted model
# reads the same value out of the prompt instead.
_CURRENT_CASE: dict[str, Any] = {}


def set_scripted_context(**values: Any) -> None:
    _CURRENT_CASE.clear()
    _CURRENT_CASE.update(values)


# ------------------------------------------------------ structured payloads


def _derive(observations: dict[str, Any]) -> dict[str, Any]:
    case = observations.get("get_return_case") or {}
    comparison = observations.get("compare_expected_and_received") or {}
    cost = observations.get("lookup_replacement_cost") or {}
    policy = observations.get("find_approved_policy") or {}

    missing = comparison.get("missing_components") or []
    failures = list(comparison.get("tool_failures") or [])
    if cost.get("error"):
        failures.append(str(cost["error"]))

    count = comparison.get("missing_component_count", len(missing))
    serial_match = bool(comparison.get("serial_match", False))
    evidence_complete = bool(comparison.get("evidence_complete", False))
    new_damage = bool(comparison.get("new_damage_present", False))
    replacement_cost = cost.get("replacement_cost_usd", comparison.get("replacement_cost_usd"))

    clean = (
        count == 1
        and serial_match
        and evidence_complete
        and not new_damage
        and not failures
        and replacement_cost is not None
    )
    if failures:
        confidence = LOW_CONFIDENCE
    elif clean:
        confidence = HIGH_CONFIDENCE
    else:
        confidence = REDUCED_CONFIDENCE

    matched_policy = policy.get("matching_policy_id")
    if matched_policy and clean:
        recommendation = "apply_policy"
    elif clean:
        recommendation = "request_decision"
    else:
        recommendation = "escalate"

    return {
        "case": case,
        "comparison": comparison,
        "cost": cost,
        "policy": policy,
        "missing": missing,
        "failures": failures,
        "count": count,
        "serial_match": serial_match,
        "evidence_complete": evidence_complete,
        "new_damage": new_damage,
        "replacement_cost": replacement_cost,
        "clean": clean,
        "confidence": confidence,
        "recommendation": recommendation,
        "matched_policy": matched_policy,
        "case_id": case.get("case_id") or comparison.get("case_id") or _CURRENT_CASE.get("case_id", ""),
    }


def _evidence_items(d: dict[str, Any]) -> list[dict[str, str]]:
    comparison = d["comparison"]
    case = d["case"]
    items = [
        {
            "label": "Kit and order",
            "value": f"{case.get('kit_name', 'unknown kit')} ({case.get('sku', '?')}) on {case.get('order_id', '?')}",
            "source_tool": "get_return_case",
        },
        {
            "label": "Serial check",
            "value": (
                f"expected {comparison.get('expected_serial', '?')}, "
                f"received {comparison.get('received_serial') or 'none recorded'} — "
                f"{'match' if d['serial_match'] else 'MISMATCH'}"
            ),
            "source_tool": "compare_expected_and_received",
        },
        {
            "label": "Components missing",
            "value": (
                ", ".join(f"{m['name']} ({m['component_id']})" for m in d["missing"])
                or "none"
            ),
            "source_tool": "compare_expected_and_received",
        },
        {
            "label": "Inspection evidence",
            "value": (
                "complete"
                if d["evidence_complete"]
                else "incomplete: " + ", ".join(comparison.get("missing_evidence_fields", []) or ["unknown"])
            ),
            "source_tool": "compare_expected_and_received",
        },
        {
            "label": "New damage",
            "value": "yes" if d["new_damage"] else "none recorded",
            "source_tool": "compare_expected_and_received",
        },
        {
            "label": "Replacement cost",
            "value": (
                f"${d['replacement_cost']:.2f} ({d['cost'].get('stock_status', 'unknown')})"
                if isinstance(d["replacement_cost"], (int, float))
                else "unavailable"
            ),
            "source_tool": "lookup_replacement_cost",
        },
        {
            "label": "Approved policy",
            "value": d["policy"].get("summary", "no active policy consulted"),
            "source_tool": "find_approved_policy",
        },
    ]
    return items


def _rationale(d: dict[str, Any]) -> str:
    if d["failures"]:
        return (
            "A supporting system failed while gathering evidence, so the picture is "
            "incomplete. Recommending escalation rather than acting on partial data."
        )
    if not d["clean"]:
        blockers = []
        if not d["serial_match"]:
            blockers.append("the serial does not match")
        if d["new_damage"]:
            blockers.append("new damage is present")
        if not d["evidence_complete"]:
            blockers.append("inspection evidence is incomplete")
        if d["count"] != 1:
            blockers.append(f"{d['count']} components are missing")
        if d["replacement_cost"] is None:
            blockers.append("no replacement cost is on file")
        return (
            "This case falls outside safe automatic handling because "
            + ", and ".join(blockers[:3])
            + ". Recommending escalation to a person."
        )
    if d["matched_policy"]:
        return (
            f"One low-cost accessory is missing and every condition of the active policy holds: "
            f"serial matches, evidence is complete, no new damage, replacement cost "
            f"${d['replacement_cost']:.2f}. Recommending the approved policy be applied."
        )
    return (
        f"One non-serialized accessory is missing at ${d['replacement_cost']:.2f}, the serial "
        "matches, evidence is complete, and there is no new damage. No approved policy covers "
        "this yet, so a person needs to decide."
    )


def build_structured_payload(model_name: str, observations: dict[str, Any]) -> dict[str, Any] | None:
    d = _derive(observations)

    if model_name == "InvestigationReport":
        return {
            "case_id": d["case_id"],
            "evidence": _evidence_items(d),
            "observed_missing_component_count": d["count"],
            "observed_serial_match": d["serial_match"],
            "observed_new_damage": d["new_damage"],
            "observed_evidence_complete": d["evidence_complete"],
            "observed_replacement_cost_usd": d["replacement_cost"],
            "matching_policy_id": d["matched_policy"],
            "recommended_action": d["recommendation"],
            "confidence": d["confidence"],
            "rationale": _rationale(d),
        }

    if model_name == "DecisionCard":
        first = d["missing"][0] if d["missing"] else {"name": "unknown component", "component_id": "?"}
        cost = d["replacement_cost"]
        cost_text = f"${cost:.2f}" if isinstance(cost, (int, float)) else "an unknown amount"
        return {
            "case_id": d["case_id"],
            "headline": (
                f"{d['case'].get('kit_name', 'Returned kit')} came back without its "
                f"{first['name'].lower()} ({cost_text})"
            ),
            "evidence": _evidence_items(d),
            "recommended_action": (
                f"Put the kit in PARTS_HOLD and raise a replacement-parts work order for "
                f"{first['name']} at {cost_text}, then close the exception."
            ),
            "uncertainty": [
                "No approved policy covers a missing accessory on this kit family yet.",
                "The customer has not been asked whether the accessory was ever received.",
            ],
            "proposed_boundaries": [
                {
                    "description": "Exactly one missing component, and it is not serialized, safety-critical, or essential",
                    "reason": "A missing body, battery, or safety part is a different decision with a different risk.",
                },
                {
                    "description": "Serial number matches and there is no new damage",
                    "reason": "Either one means the wrong unit or a damaged unit came back, which a person should see.",
                },
                {
                    "description": "Replacement cost is $25.00 or less",
                    "reason": "Caps the spend this decision can authorize without another human look.",
                },
                {
                    "description": "All required inspection evidence is present",
                    "reason": "Acting on an incomplete inspection is how quiet errors get expensive.",
                },
            ],
            "why_human_must_decide": (
                "This is the first time this exception has been seen. Nobody has authorized "
                "spending money on replacement parts without a person looking, and the boundary "
                "for when that is acceptable has not been set."
            ),
            "estimated_cost_usd": cost if isinstance(cost, (int, float)) else None,
        }

    if model_name == "PolicyProposal":
        cost = d["replacement_cost"]
        threshold = 25.0
        if isinstance(cost, (int, float)) and cost > threshold:
            threshold = float(min(50.0, round(cost + 1.0, 2)))
        return {
            "name": "Single low-cost accessory replacement",
            "description": (
                "When exactly one non-serialized, non-safety-critical, non-essential accessory "
                "is missing from a returned kit, the serial matches, there is no new damage, the "
                "inspection evidence is complete, and the replacement part costs "
                f"${threshold:.2f} or less: hold the kit for parts, raise a replacement-parts "
                "work order, and close the exception."
            ),
            "conditions": [
                {"field": "missing_component_count", "operator": "eq", "value": 1},
                {"field": "missing_component_serialized", "operator": "eq", "value": False},
                {"field": "missing_component_safety_critical", "operator": "eq", "value": False},
                {"field": "missing_component_essential", "operator": "eq", "value": False},
                {"field": "serial_match", "operator": "eq", "value": True},
                {"field": "new_damage_present", "operator": "eq", "value": False},
                {"field": "evidence_complete", "operator": "eq", "value": True},
                {"field": "replacement_cost_usd", "operator": "lte", "value": threshold},
            ],
            "max_cost_usd": threshold,
            "min_confidence": 0.75,
            "justification": (
                "This mirrors the decision that was just approved and nothing wider. Every "
                "condition is one the supervisor named, and the spend cap matches the "
                "replacement cost that was actually approved."
            ),
            "expected_effect": (
                "Cases identical in shape to this one resolve without an interruption; anything "
                "with a serial mismatch, damage, missing evidence, a serialized or safety part, "
                "more than one missing item, or a higher cost still escalates."
            ),
        }

    return None


def _closing_text(observations: dict[str, Any]) -> str:
    d = _derive(observations)
    return _rationale(d)


# --------------------------------------------------------------- stream events


def _tool_use_events(name: str, payload: dict[str, Any], index: int = 0) -> list[StreamEvent]:
    """Emit the Bedrock-shaped stream events for a single tool call."""
    tool_use_id = f"scripted_{name}_{index}"
    return [
        {"messageStart": {"role": "assistant"}},
        {
            "contentBlockStart": {
                "contentBlockIndex": 0,
                "start": {"toolUse": {"toolUseId": tool_use_id, "name": name}},
            }
        },
        {
            "contentBlockDelta": {
                "contentBlockIndex": 0,
                "delta": {"toolUse": {"input": json.dumps(payload)}},
            }
        },
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "tool_use"}},
    ]
