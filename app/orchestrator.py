"""The golden path.

    event -> investigate -> reconcile -> guardrails -> policy?
      -> yes: execute, verify, close
      -> no : decision card -> human -> propose -> replay -> human activates

Everything that can act lives here, not in a tool. `execute_approved_policy`,
`verify_action`, and the decision/teaching flow are ordinary Python functions
that the model has no way to call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db import Connection

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app import audit, db
from app.adapters import warehouse
from app.adapters.returns_system import AdapterError
from app.agent.build import decision_card_agent, investigation_agent, policy_proposal_agent
from app.agent.providers import provider_label
from app.agent.tools import AgentContext
from app.audit import AuditEventType
from app.config import settings
from app.domain import (
    ActionResult,
    CaseFacts,
    DecisionCard,
    ExceptionStatus,
    HandlingResult,
    InvestigationReport,
    Outcome,
    PolicyProposal,
    PolicyStatus,
    VerificationResult,
)
from app.facts import derive_facts, reconcile
from app.policy import store as policy_store
from app.policy.diff import diff_policies
from app.policy.engine import select_matching_policies
from app.policy.guardrails import evaluate_guardrails
from app.policy.proposal import proposal_to_payload, revised_payload
from app.policy.replay import replay_candidate_policy
from app.policy.schema import PolicyDefinition, spec_for, PolicyValidationError


class OrchestratorError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _trace_id() -> str:
    return f"trc_{uuid.uuid4().hex[:12]}"


def idempotency_key(*parts: str) -> str:
    """Stable key for a state-changing action.

    Derived only from the case, the policy version, and the action, so the same
    action on the same case under the same policy always produces the same key —
    a retry or a duplicate event can never create a second work order.
    """
    material = "|".join(parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _prepare_scripted_context(**values: Any) -> None:
    if settings.is_offline_provider:
        from app.agent.providers.scripted import set_scripted_context

        set_scripted_context(**values)


# ---------------------------------------------------------------- exceptions


def _ensure_exception(
    conn: "Connection", case_id: str, trace_id: str, event_key: str
) -> tuple[str, bool]:
    """Create the exception row, or return the existing one for a duplicate event.

    The insert is conditional rather than select-then-insert: two events with the
    same key arriving at once would both pass a prior SELECT and one would then
    fail on the unique index. `ON CONFLICT DO NOTHING RETURNING` decides the race
    in the database, so the loser is reported as a duplicate rather than an error.
    """
    exception_id = f"exc_{uuid.uuid4().hex[:12]}"
    now = _now()
    inserted = conn.execute(
        """INSERT INTO exceptions (exception_id, case_id, trace_id, status, event_key,
                                   created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (event_key) DO NOTHING
           RETURNING exception_id""",
        (exception_id, case_id, trace_id, ExceptionStatus.NEW, event_key, now, now),
    ).fetchone()
    if inserted is not None:
        return inserted["exception_id"], False

    existing = conn.execute(
        "SELECT exception_id FROM exceptions WHERE event_key = ?", (event_key,)
    ).fetchone()
    if existing is None:  # pragma: no cover - the row must exist to have conflicted
        raise OrchestratorError(f"event key '{event_key}' conflicted but no row is present")
    return existing["exception_id"], True


def _set_status(
    conn: "Connection",
    exception_id: str,
    status: ExceptionStatus,
    *,
    summary: str | None = None,
    escalation_reasons: list[str] | None = None,
    applied_policy_id: str | None = None,
) -> None:
    conn.execute(
        """UPDATE exceptions
              SET status = ?,
                  summary = COALESCE(?, summary),
                  escalation_reasons = COALESCE(?, escalation_reasons),
                  applied_policy_id = COALESCE(?, applied_policy_id),
                  updated_at = ?
            WHERE exception_id = ?""",
        (
            status,
            summary,
            json.dumps(escalation_reasons) if escalation_reasons is not None else None,
            applied_policy_id,
            _now(),
            exception_id,
        ),
    )


# ------------------------------------------------------------------- actions


def execute_approved_policy(
    conn: "Connection",
    case_id: str,
    policy_id: str,
    idem_key: str,
    *,
    trace_id: str,
    exception_id: str,
    facts: CaseFacts,
) -> list[ActionResult]:
    """Run the actions of an ACTIVE policy. The only path to a business write.

    Refuses unless the policy is active. Refuses if the facts no longer satisfy
    it. Every action is keyed for idempotency.
    """
    record = policy_store.get(conn, policy_id)
    if record.status != "active":
        raise OrchestratorError(
            f"refusing to execute policy {policy_id}: status is '{record.status}', not 'active'"
        )

    definition: PolicyDefinition = record.definition
    spec = spec_for(definition.family)
    results: list[ActionResult] = []

    for action in definition.actions:
        key = idempotency_key(idem_key, action.type)
        try:
            if action.type == "close_exception":
                # Closing the case is the machinery's own act, not the domain's.
                _set_status(
                    conn,
                    exception_id,
                    ExceptionStatus.RESOLVED,
                    applied_policy_id=policy_id,
                    summary=f"resolved automatically under {record.label}",
                )
                result = ActionResult(
                    action=f"close_exception:{action.resolution_code}",
                    ok=True,
                    idempotency_key=key,
                    detail=f"exception closed under {record.label}",
                    reference=exception_id,
                )
            else:
                out = spec.execute(conn, action, facts=facts, idem_key=key)
                result = ActionResult(
                    action=out["label"],
                    ok=True,
                    idempotency_key=key,
                    detail=out["detail"],
                    duplicate_suppressed=out["duplicate_suppressed"],
                    reference=out["reference"],
                )
        except AdapterError as exc:
            audit.record(
                conn,
                trace_id=trace_id,
                event_type=AuditEventType.ACTION_FAILED,
                actor="system",
                case_id=case_id,
                exception_id=exception_id,
                policy_id=policy_id,
                payload={"action": action.type, "error": str(exc), "idempotency_key": key},
            )
            results.append(
                ActionResult(action=action.type, ok=False, idempotency_key=key, detail=str(exc))
            )
            return results

        audit.record(
            conn,
            trace_id=trace_id,
            event_type=(
                AuditEventType.ACTION_DUPLICATE
                if result.duplicate_suppressed
                else AuditEventType.ACTION_EXECUTED
            ),
            actor="system",
            case_id=case_id,
            exception_id=exception_id,
            policy_id=policy_id,
            payload={
                "action": result.action,
                "detail": result.detail,
                "idempotency_key": key,
                "duplicate_suppressed": result.duplicate_suppressed,
                "policy_version": record.version,
            },
        )
        results.append(result)

    return results


def verify_action(
    conn: "Connection",
    case_id: str,
    policy_id: str,
    *,
    trace_id: str,
    exception_id: str,
) -> VerificationResult:
    """Read the business systems back and confirm the writes actually landed."""
    record = policy_store.get(conn, policy_id)
    # The domain reads its own systems back; the exception itself is ours.
    checks, failures = spec_for(record.definition.family).verify(conn, case_id)

    row = conn.execute(
        "SELECT status, applied_policy_id FROM exceptions WHERE exception_id = ?", (exception_id,)
    ).fetchone()
    if row and row["status"] == ExceptionStatus.RESOLVED:
        checks.append("exception is closed")
    else:
        failures.append(f"exception status is '{row['status'] if row else 'missing'}', expected resolved")

    if row and row["applied_policy_id"] == policy_id:
        checks.append(f"closed against policy {policy_id}")
    else:
        failures.append("exception is not linked to the policy version that closed it")

    result = VerificationResult(ok=not failures, checks=checks, failures=failures)
    audit.record(
        conn,
        trace_id=trace_id,
        event_type=(
            AuditEventType.VERIFICATION_PASSED if result.ok else AuditEventType.VERIFICATION_FAILED
        ),
        actor="system",
        case_id=case_id,
        exception_id=exception_id,
        policy_id=policy_id,
        payload={"checks": checks, "failures": failures},
    )
    return result


# ----------------------------------------------------------------- the path


@dataclass
class _AgentOutcome:
    report: InvestigationReport | None
    error: str | None
    tool_calls: list[str]
    tool_failures: list[str]


def _record_agent_run(
    ctx: AgentContext, step: str, result: Any, started: float, calls_before: int
) -> None:
    """Record what one agent invocation consumed, for the usage dashboard.

    Token counts are whatever the model provider reported. The offline scripted
    model reports none, so they are recorded as zero rather than estimated. Tool
    calls are counted from the context, not from Strands' tool metrics, which also
    count the internal tool Strands uses to return structured output.
    """
    metrics = getattr(result, "metrics", None)
    usage = dict(getattr(metrics, "accumulated_usage", None) or {})
    latency = dict(getattr(metrics, "accumulated_metrics", None) or {})
    audit.record(
        ctx.conn,
        trace_id=ctx.trace_id,
        event_type=AuditEventType.AGENT_RUN,
        actor="agent",
        case_id=ctx.case_id,
        exception_id=ctx.exception_id,
        payload={
            "step": step,
            "provider": provider_label(),
            "input_tokens": int(usage.get("inputTokens") or 0),
            "output_tokens": int(usage.get("outputTokens") or 0),
            "total_tokens": int(usage.get("totalTokens") or 0),
            # Prompt-cache traffic, when the provider caches; Bedrock reports it in its own fields.
            "cache_read_input_tokens": int(usage.get("cacheReadInputTokens") or 0),
            "cache_write_input_tokens": int(usage.get("cacheWriteInputTokens") or 0),
            "model_latency_ms": int(latency.get("latencyMs") or 0),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "cycles": int(getattr(metrics, "cycle_count", 0) or 0),
            "tool_calls": len(ctx.calls) - calls_before,
        },
    )


def _run_investigation(ctx: AgentContext, case_id: str) -> _AgentOutcome:
    _prepare_scripted_context(case_id=case_id)
    agent = investigation_agent(ctx)
    started, calls_before = time.perf_counter(), len(ctx.calls)
    try:
        result = agent(
            f"Investigate return case {case_id} and report what you found.",
            structured_output_model=InvestigationReport,
        )
    except Exception as exc:  # model timeout, transport error, malformed output
        return _AgentOutcome(None, f"{type(exc).__name__}: {exc}", ctx.tool_names, ctx.failures)

    _record_agent_run(ctx, "investigation", result, started, calls_before)
    ctx.transcript = list(agent.messages)
    report = result.structured_output
    if not isinstance(report, InvestigationReport):
        return _AgentOutcome(
            None, "agent did not return a typed InvestigationReport", ctx.tool_names, ctx.failures
        )
    return _AgentOutcome(report, None, ctx.tool_names, ctx.failures)


def handle_event(
    case_id: str,
    *,
    event_key: str | None = None,
    conn: "Connection" | None = None,
    reuse_exception_id: str | None = None,
) -> HandlingResult:
    """Handle one inbound exception event, end to end.

    `reuse_exception_id` re-runs the path against an exception that already
    exists, instead of opening a new one. Used when a policy is activated and
    the case that taught it should now be handled under it.
    """
    if conn is not None:
        return _handle_event(conn, case_id, event_key, reuse_exception_id)
    with db.session() as owned:
        return _handle_event(owned, case_id, event_key, reuse_exception_id)


def _handle_event(
    conn: "Connection",
    case_id: str,
    event_key: str | None,
    reuse_exception_id: str | None = None,
) -> HandlingResult:
    started = time.perf_counter()
    trace_id = _trace_id()
    key = event_key or f"evt::{case_id}"

    known = conn.execute(
        "SELECT 1 FROM return_cases WHERE case_id = ?", (case_id,)
    ).fetchone()
    if known is None:
        # An event for a case the returns system has never heard of. There is
        # nothing to investigate and nothing to act on: say so and stop.
        reason = f"unknown case '{case_id}': no such return case in the returns system"
        audit.record(
            conn,
            trace_id=trace_id,
            event_type=AuditEventType.EXCEPTION_ESCALATED,
            actor="system",
            payload={"event_key": key, "reasons": [reason]},
        )
        return HandlingResult(
            case_id=case_id,
            exception_id="",
            trace_id=trace_id,
            outcome=Outcome.ESCALATED,
            status=ExceptionStatus.ESCALATED,
            escalation_reasons=[reason],
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    if reuse_exception_id:
        exception_id, duplicate = reuse_exception_id, False
    else:
        exception_id, duplicate = _ensure_exception(conn, case_id, trace_id, key)

    if duplicate:
        audit.record(
            conn,
            trace_id=trace_id,
            event_type=AuditEventType.EVENT_DUPLICATE,
            actor="system",
            case_id=case_id,
            exception_id=exception_id,
            payload={"event_key": key, "detail": "event already handled; no action taken"},
        )
        row = conn.execute(
            "SELECT status, applied_policy_id, escalation_reasons FROM exceptions WHERE exception_id = ?",
            (exception_id,),
        ).fetchone()
        status = ExceptionStatus(row["status"])
        return HandlingResult(
            case_id=case_id,
            exception_id=exception_id,
            trace_id=trace_id,
            outcome=_outcome_for(status),
            status=status,
            policy_id=row["applied_policy_id"],
            escalation_reasons=json.loads(row["escalation_reasons"] or "[]"),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    audit.record(
        conn,
        trace_id=trace_id,
        event_type=AuditEventType.EVENT_RECEIVED,
        actor="returns_dock",
        case_id=case_id,
        exception_id=exception_id,
        payload={"event_key": key, "source": "SYNTHETIC returns dock check-in event"},
    )
    _set_status(conn, exception_id, ExceptionStatus.INVESTIGATING)
    audit.record(
        conn,
        trace_id=trace_id,
        event_type=AuditEventType.INVESTIGATION_STARTED,
        actor="agent",
        case_id=case_id,
        exception_id=exception_id,
        payload={"provider": settings.model_provider},
    )

    ctx = AgentContext(conn=conn, trace_id=trace_id, case_id=case_id, exception_id=exception_id)
    outcome = _run_investigation(ctx, case_id)

    def escalate(reasons: list[str], report: InvestigationReport | None = None) -> HandlingResult:
        _set_status(
            conn,
            exception_id,
            ExceptionStatus.ESCALATED,
            summary=reasons[0] if reasons else "escalated",
            escalation_reasons=reasons,
        )
        audit.record(
            conn,
            trace_id=trace_id,
            event_type=AuditEventType.EXCEPTION_ESCALATED,
            actor="system",
            case_id=case_id,
            exception_id=exception_id,
            payload={"reasons": reasons},
        )
        return HandlingResult(
            case_id=case_id,
            exception_id=exception_id,
            trace_id=trace_id,
            outcome=Outcome.ESCALATED,
            status=ExceptionStatus.ESCALATED,
            escalation_reasons=reasons,
            report=report,
            tool_calls=ctx.tool_names,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    if outcome.error is not None:
        return escalate([f"agent investigation failed: {outcome.error}"])

    report = outcome.report
    assert report is not None

    # Facts come from the systems, not from the agent.
    try:
        facts = derive_facts(conn, case_id)
    except AdapterError as exc:
        return escalate([f"could not derive case facts: {exc}"], report)

    audit.record(
        conn,
        trace_id=trace_id,
        event_type=AuditEventType.INVESTIGATION_COMPLETED,
        actor="agent",
        case_id=case_id,
        exception_id=exception_id,
        payload={
            "recommended_action": report.recommended_action,
            "confidence": report.confidence,
            "rationale": report.rationale,
            "tools_called": ctx.tool_names,
        },
    )

    discrepancies = reconcile(report, facts)
    if discrepancies:
        audit.record(
            conn,
            trace_id=trace_id,
            event_type=AuditEventType.RECONCILIATION_MISMATCH,
            actor="system",
            case_id=case_id,
            exception_id=exception_id,
            payload={"discrepancies": discrepancies},
        )
        return escalate(
            ["agent report does not reconcile with the source systems"] + discrepancies, report
        )

    active = [(p.policy_id, p.definition) for p in policy_store.list_active(conn)]
    matches = select_matching_policies(active, facts)

    guard = evaluate_guardrails(
        facts,
        confidence=report.confidence,
        tool_failures=tuple(outcome.tool_failures),
        matching_policy_count=len(matches),
    )

    if len(matches) > 1:
        audit.record(
            conn,
            trace_id=trace_id,
            event_type=AuditEventType.POLICY_CONFLICT,
            actor="system",
            case_id=case_id,
            exception_id=exception_id,
            payload={"policy_ids": [m[0] for m in matches]},
        )

    if guard.blocked:
        audit.record(
            conn,
            trace_id=trace_id,
            event_type=AuditEventType.GUARDRAIL_BLOCKED,
            actor="system",
            case_id=case_id,
            exception_id=exception_id,
            payload={"reasons": list(guard.reasons)},
        )
        return escalate(list(guard.reasons), report)

    if matches:
        policy_id, definition, _match = matches[0]
        record = policy_store.get(conn, policy_id)
        if report.confidence < definition.min_confidence:
            return escalate(
                [
                    f"agent confidence {report.confidence:.2f} is below the policy's own minimum "
                    f"{definition.min_confidence:.2f}"
                ],
                report,
            )
        audit.record(
            conn,
            trace_id=trace_id,
            event_type=AuditEventType.POLICY_MATCHED,
            actor="system",
            case_id=case_id,
            exception_id=exception_id,
            policy_id=policy_id,
            payload={"policy": record.label, "conditions": definition.condition_summary()},
        )
        base_key = idempotency_key(case_id, policy_id, str(record.version))
        actions = execute_approved_policy(
            conn,
            case_id,
            policy_id,
            base_key,
            trace_id=trace_id,
            exception_id=exception_id,
            facts=facts,
        )
        if not all(a.ok for a in actions):
            failed = next(a for a in actions if not a.ok)
            return escalate([f"action failed during automatic handling: {failed.detail}"], report)

        verification = verify_action(
            conn, case_id, policy_id, trace_id=trace_id, exception_id=exception_id
        )
        if not verification.ok:
            return escalate(
                ["verification failed after automatic action"] + verification.failures, report
            )

        audit.record(
            conn,
            trace_id=trace_id,
            event_type=AuditEventType.EXCEPTION_RESOLVED,
            actor="system",
            case_id=case_id,
            exception_id=exception_id,
            policy_id=policy_id,
            payload={"policy": record.label, "actions": [a.action for a in actions]},
        )
        return HandlingResult(
            case_id=case_id,
            exception_id=exception_id,
            trace_id=trace_id,
            outcome=Outcome.AUTO_RESOLVED,
            status=ExceptionStatus.RESOLVED,
            policy_id=policy_id,
            actions=actions,
            verification=verification,
            report=report,
            tool_calls=ctx.tool_names,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    # No approved policy applies.
    audit.record(
        conn,
        trace_id=trace_id,
        event_type=AuditEventType.POLICY_NOT_FOUND,
        actor="system",
        case_id=case_id,
        exception_id=exception_id,
        payload={"active_policies": len(active)},
    )

    # A near-match is not an invitation to widen the policy. Once this exception
    # family has an approved boundary, a case that falls outside it goes to a
    # person as an escalation, naming the condition it failed. Only a family
    # with no approved policy at all produces a fresh decision card.
    if active:
        near = _near_miss_reasons(active, facts)
        return escalate(
            ["case falls outside every approved policy for this exception family"] + near,
            report,
        )
    card = _build_decision_card(ctx, conn, case_id, exception_id, trace_id)
    if card is None:
        return escalate(["agent could not produce a decision card"], report)

    _set_status(
        conn,
        exception_id,
        ExceptionStatus.WAITING_DECISION,
        summary=card.headline,
    )
    return HandlingResult(
        case_id=case_id,
        exception_id=exception_id,
        trace_id=trace_id,
        outcome=Outcome.DECISION_REQUESTED,
        status=ExceptionStatus.WAITING_DECISION,
        decision_card=card,
        report=report,
        tool_calls=ctx.tool_names,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _outcome_for(status: ExceptionStatus) -> Outcome:
    match status:
        case ExceptionStatus.RESOLVED:
            return Outcome.AUTO_RESOLVED
        case ExceptionStatus.ESCALATED:
            return Outcome.ESCALATED
        case _:
            return Outcome.DECISION_REQUESTED


def _build_decision_card(
    ctx: AgentContext,
    conn: "Connection",
    case_id: str,
    exception_id: str,
    trace_id: str,
) -> DecisionCard | None:
    agent = decision_card_agent(ctx)
    # Carry the investigation transcript so the card is grounded in the same
    # tool results rather than a fresh guess.
    agent.messages = list(ctx.transcript)
    started, calls_before = time.perf_counter(), len(ctx.calls)
    try:
        result = agent(
            "Produce the decision card for this case.", structured_output_model=DecisionCard
        )
    except Exception as exc:
        audit.record(
            conn,
            trace_id=trace_id,
            event_type=AuditEventType.TOOL_FAILED,
            actor="agent",
            case_id=case_id,
            exception_id=exception_id,
            payload={"step": "decision_card", "error": f"{type(exc).__name__}: {exc}"},
        )
        return None

    _record_agent_run(ctx, "decision_card", result, started, calls_before)
    card = result.structured_output
    if not isinstance(card, DecisionCard):
        return None

    decision_card_id = f"dec_{uuid.uuid4().hex[:12]}"
    conn.execute(
        """INSERT INTO decision_cards (decision_card_id, exception_id, payload, created_at)
           VALUES (?, ?, ?, ?)""",
        (decision_card_id, exception_id, card.model_dump_json(), _now()),
    )
    audit.record(
        conn,
        trace_id=trace_id,
        event_type=AuditEventType.DECISION_CARD_CREATED,
        actor="agent",
        case_id=case_id,
        exception_id=exception_id,
        payload={
            "decision_card_id": decision_card_id,
            "headline": card.headline,
            "recommended_action": card.recommended_action,
            "boundaries": [b.description for b in card.proposed_boundaries],
        },
    )
    return card


def _near_miss_reasons(
    active: list[tuple[str, PolicyDefinition]], facts: CaseFacts
) -> list[str]:
    """Name the conditions that kept each active policy from applying."""
    from app.policy.engine import match_policy

    reasons: list[str] = []
    view = facts.policy_view()
    for policy_id, definition in active:
        result = match_policy(definition, facts)
        for unmet in result.unmet:
            field = unmet.split(" ", 1)[0]
            observed = view.get(field)
            reasons.append(f"'{definition.name}' requires {unmet}; this case has {field}={observed}")
    return reasons


# ------------------------------------------------------------ teaching flow


@dataclass
class TeachResult:
    policy_id: str
    definition: PolicyDefinition
    replay: dict[str, Any]
    proposal: PolicyProposal | None
    ready_to_activate: bool
    blocking_reasons: list[str]


def get_decision_card(conn: "Connection", exception_id: str) -> tuple[str, DecisionCard] | None:
    row = conn.execute(
        """SELECT decision_card_id, payload FROM decision_cards
            WHERE exception_id = ? ORDER BY created_at DESC LIMIT 1""",
        (exception_id,),
    ).fetchone()
    if row is None:
        return None
    return row["decision_card_id"], DecisionCard.model_validate_json(row["payload"])


def record_decision(
    conn: "Connection", exception_id: str, *, outcome: str, decided_by: str
) -> str:
    """Record the human's decision on a card. Does not itself change any policy."""
    found = get_decision_card(conn, exception_id)
    if found is None:
        raise OrchestratorError(f"no decision card for exception '{exception_id}'")
    decision_card_id, card = found

    row = conn.execute(
        "SELECT case_id, trace_id FROM exceptions WHERE exception_id = ?", (exception_id,)
    ).fetchone()
    if row is None:
        raise OrchestratorError(f"exception '{exception_id}' not found")

    conn.execute(
        "UPDATE decision_cards SET outcome = ?, decided_by = ?, decided_at = ? WHERE decision_card_id = ?",
        (outcome, decided_by, _now(), decision_card_id),
    )
    audit.record(
        conn,
        trace_id=row["trace_id"],
        event_type=AuditEventType.DECISION_RECORDED,
        actor=decided_by,
        case_id=row["case_id"],
        exception_id=exception_id,
        payload={"decision_card_id": decision_card_id, "outcome": outcome,
                 "headline": card.headline},
    )
    return decision_card_id


def approve_and_teach(
    conn: "Connection", exception_id: str, *, decided_by: str
) -> TeachResult:
    """Human approved the recommendation. Ask the agent to propose a policy.

    The result is a **candidate**. It is inert. Nothing here activates anything.
    """
    row = conn.execute(
        "SELECT case_id, trace_id FROM exceptions WHERE exception_id = ?", (exception_id,)
    ).fetchone()
    if row is None:
        raise OrchestratorError(f"exception '{exception_id}' not found")
    case_id, trace_id = row["case_id"], row["trace_id"]

    decision_card_id = record_decision(
        conn, exception_id, outcome="approve_and_teach", decided_by=decided_by
    )

    ctx = AgentContext(conn=conn, trace_id=trace_id, case_id=case_id, exception_id=exception_id)
    facts = derive_facts(conn, case_id)
    _prepare_scripted_context(
        case_id=case_id,
        candidate_policy=_provisional_policy_payload(facts),
    )

    agent = policy_proposal_agent(ctx)
    started, calls_before = time.perf_counter(), len(ctx.calls)
    result = agent(
        (
            f"The supervisor approved the recommended action on case {case_id}. "
            "Propose the narrowest policy that covers this decision and nothing wider."
        ),
        structured_output_model=PolicyProposal,
    )
    _record_agent_run(ctx, "policy_proposal", result, started, calls_before)
    proposal = result.structured_output
    if not isinstance(proposal, PolicyProposal):
        raise OrchestratorError("agent did not return a typed PolicyProposal")

    payload = proposal_to_payload(proposal)
    record = policy_store.create_candidate(
        conn,
        payload=payload,
        trace_id=trace_id,
        origin_case_id=case_id,
        origin_decision_id=decision_card_id,
    )

    report = replay_candidate_policy(conn, record.definition)
    policy_store.attach_replay_report(conn, record.policy_id, report.to_dict(), trace_id=trace_id)

    return TeachResult(
        policy_id=record.policy_id,
        definition=record.definition,
        replay=report.to_dict(),
        proposal=proposal,
        ready_to_activate=report.passed,
        blocking_reasons=report.blocking_reasons,
    )


def _provisional_policy_payload(facts: CaseFacts) -> dict[str, Any]:
    """The candidate the scripted agent dry-runs through `replay_candidate_policy`.

    Derived from the case that was just approved, so the agent's own replay call
    exercises the real evaluator rather than a hypothetical. It has the shape of a
    `PolicyProposal`, the same as a hosted model's replay call: conditions and a
    spend cap, with the fixed actions added by the tool.
    """
    threshold = 25.0
    if facts.replacement_cost_usd is not None and facts.replacement_cost_usd > threshold:
        threshold = min(50.0, round(facts.replacement_cost_usd + 1.0, 2))
    return {
        "name": "Single low-cost accessory replacement",
        "description": (
            "Exactly one missing non-serialized accessory, clean evidence, matching serial, "
            f"no new damage, replacement cost ${threshold:.2f} or less."
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
    }


def activate_policy(
    conn: "Connection", policy_id: str, *, approval_token: str, activated_by: str
) -> policy_store.PolicyRecord:
    """Human activation. The only transition from candidate to active."""
    record = policy_store.get(conn, policy_id)
    trace_id = _trace_id()
    if record.origin_case_id:
        row = conn.execute(
            "SELECT trace_id FROM exceptions WHERE case_id = ? ORDER BY created_at LIMIT 1",
            (record.origin_case_id,),
        ).fetchone()
        if row:
            trace_id = row["trace_id"]
    activated = policy_store.activate(
        conn,
        policy_id,
        approval_token=approval_token,
        activated_by=activated_by,
        trace_id=trace_id,
    )

    # The supervisor approved the action on the case that taught this policy, so
    # that case should now be handled under it rather than sitting in the inbox.
    # It runs the same path as any other case: guardrails, policy match,
    # execution, verification. If it no longer qualifies, it escalates like
    # anything else.
    if record.origin_case_id:
        origin = conn.execute(
            """SELECT exception_id FROM exceptions
                WHERE case_id = ? AND status = ? ORDER BY created_at LIMIT 1""",
            (record.origin_case_id, ExceptionStatus.WAITING_DECISION),
        ).fetchone()
        if origin is not None:
            handle_event(
                record.origin_case_id,
                conn=conn,
                event_key=f"evt::{record.origin_case_id}::activated::{policy_id}",
                reuse_exception_id=origin["exception_id"],
            )

    return activated


def reject_policy(
    conn: "Connection", policy_id: str, *, actor: str, reason: str = ""
) -> policy_store.PolicyRecord:
    return policy_store.reject(conn, policy_id, actor=actor, trace_id=_trace_id(), reason=reason)


def escalate_manually(
    conn: "Connection", exception_id: str, *, actor: str, reason: str
) -> None:
    row = conn.execute(
        "SELECT case_id, trace_id FROM exceptions WHERE exception_id = ?", (exception_id,)
    ).fetchone()
    if row is None:
        raise OrchestratorError(f"exception '{exception_id}' not found")
    _set_status(
        conn,
        exception_id,
        ExceptionStatus.ESCALATED,
        summary=reason,
        escalation_reasons=[reason],
    )
    audit.record(
        conn,
        trace_id=row["trace_id"],
        event_type=AuditEventType.EXCEPTION_ESCALATED,
        actor=actor,
        case_id=row["case_id"],
        exception_id=exception_id,
        payload={"reasons": [reason], "manual": True},
    )


def revise_candidate(
    conn: "Connection",
    policy_id: str,
    *,
    max_cost_usd: float,
    min_confidence: float,
    kit_category: str | None,
    revised_by: str,
    note: str = "",
) -> TeachResult:
    """A human adjusts a proposed policy before deciding whether to activate it.

    The original candidate is superseded, never edited: the record keeps what the
    agent proposed alongside what the person changed. The revision then goes
    through exactly the same gate as the original — schema validation, then
    replay — so a revised policy that would have actioned a case wrongly is just
    as un-activatable as a proposed one.
    """
    original = policy_store.get(conn, policy_id)
    if original.status != PolicyStatus.CANDIDATE:
        raise OrchestratorError(
            f"only a candidate may be revised; policy {policy_id} is '{original.status}'"
        )

    trace_id = _trace_id()
    if original.origin_case_id:
        row = conn.execute(
            "SELECT trace_id FROM exceptions WHERE case_id = ? ORDER BY created_at LIMIT 1",
            (original.origin_case_id,),
        ).fetchone()
        if row:
            trace_id = row["trace_id"]

    payload = revised_payload(
        original.definition,
        max_cost_usd=max_cost_usd,
        min_confidence=min_confidence,
        kit_category=kit_category or None,
    )

    revision = policy_store.create_candidate(
        conn,
        payload=payload,
        trace_id=trace_id,
        origin_case_id=original.origin_case_id,
        origin_decision_id=original.origin_decision_id,
        actor=revised_by,
        revised_from_policy_id=policy_id,
        revision_note=note or None,
    )
    policy_store.supersede(
        conn, policy_id, replaced_by=revision.policy_id, actor=revised_by, trace_id=trace_id
    )

    change = diff_policies(
        original.definition,
        revision.definition,
        baseline_label=f"proposed v{original.version}",
        candidate_label=f"revised v{revision.version}",
    )

    # A person tightening the agent's proposal is not held to the coverage floor;
    # a person loosening it is. Neither is ever exempt from zero false actions.
    report = replay_candidate_policy(
        conn, revision.definition, enforce_coverage=change.widens
    )
    policy_store.attach_replay_report(conn, revision.policy_id, report.to_dict(), trace_id=trace_id)
    audit.record(
        conn,
        trace_id=trace_id,
        event_type=AuditEventType.POLICY_REVISED,
        actor=revised_by,
        case_id=original.origin_case_id,
        policy_id=revision.policy_id,
        payload={
            "revised_from": policy_id,
            "note": note,
            "summary": change.summary,
            "widens": change.widens,
            "changes": [
                {"field": r.label, "before": r.before, "after": r.after, "kind": r.kind.value}
                for r in change.changed_rows
            ],
        },
    )

    return TeachResult(
        policy_id=revision.policy_id,
        definition=revision.definition,
        replay=report.to_dict(),
        proposal=None,
        ready_to_activate=report.passed,
        blocking_reasons=report.blocking_reasons,
    )


def policy_diff_for(conn: "Connection", record: policy_store.PolicyRecord):
    """Diff a policy version against whatever it should be read against.

    A revision is most usefully compared to the version it revised. Anything else
    is compared to the active policy it would replace — or to nothing, when it
    would be the first.
    """
    if record.revised_from_policy_id:
        try:
            previous = policy_store.get(conn, record.revised_from_policy_id)
            return diff_policies(
                previous.definition,
                record.definition,
                baseline_label=f"proposed v{previous.version}",
                candidate_label=f"revised v{record.version}",
            )
        except KeyError:
            pass

    active = [p for p in policy_store.list_active(conn) if p.policy_id != record.policy_id]
    baseline = active[0] if active else None
    return diff_policies(
        baseline.definition if baseline else None,
        record.definition,
        baseline_label=f"active v{baseline.version}" if baseline else "no active policy",
        candidate_label=f"v{record.version}",
    )
