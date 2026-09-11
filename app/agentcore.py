"""Amazon Bedrock AgentCore Runtime entrypoint.

Kept as a thin, optional adapter so the local golden path stays the source of
truth. Importing this module does not require `bedrock-agentcore` to be
installed; the dependency is only needed to actually serve.

Deployment status: **deployed** to AgentCore Runtime in us-west-2. AgentCore runs
`agentcore_main.py` at the package root, which calls `build_app()` below; the project
config is in `agentcore/`. See `docs/deployment-agentcore.md`. Each runtime session
seeds its own SQLite database, so state does not carry across sessions.

Run locally (serves on the AgentCore contract, no AWS involved):

    pip install -e ".[agentcore]"
    python -m app.agentcore
"""

from __future__ import annotations

import re
from typing import Any

from app import db, seed
from app.config import settings
from app.orchestrator import handle_event

_CASE_ID = re.compile(r"\bCASE-\d+\b", re.IGNORECASE)


def invoke(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle one AgentCore invocation.

    Payload shape:
        {"case_id": "CASE-2002", "event_key": "optional-idempotency-key"}

    The SDK examples in the AgentCore documentation send {"prompt": "..."}
    instead, so a case ID named in a prompt is accepted too.

    The response is the same `HandlingResult` the local path produces, so the
    runtime is a transport detail rather than a second implementation.
    """
    case_id = payload.get("case_id")
    if not case_id and isinstance(payload.get("prompt"), str):
        match = _CASE_ID.search(payload["prompt"])
        case_id = match.group(0).upper() if match else None
    if not case_id:
        return {"error": "payload must include 'case_id', or a prompt naming a case such as CASE-2001"}

    db.init_db()
    with db.read_only() as conn:
        if conn.execute("SELECT COUNT(*) AS c FROM return_cases").fetchone()["c"] == 0:
            seed.seed()

    result = handle_event(case_id, event_key=payload.get("event_key"))
    return {
        "case_id": result.case_id,
        "outcome": result.outcome.value,
        "status": result.status.value,
        "policy_id": result.policy_id,
        "escalation_reasons": result.escalation_reasons,
        "actions": [a.model_dump() for a in result.actions],
        "verification": result.verification.model_dump() if result.verification else None,
        "decision_card": result.decision_card.model_dump() if result.decision_card else None,
        "tool_calls": result.tool_calls,
        "trace_id": result.trace_id,
        "duration_ms": result.duration_ms,
        "model_provider": settings.model_provider,
        "database": db.backend_name(),
    }


def build_app():  # pragma: no cover - requires the optional dependency
    """Wrap `invoke` in the AgentCore runtime app."""
    try:
        from bedrock_agentcore.runtime import BedrockAgentCoreApp
    except ImportError as exc:
        raise RuntimeError(
            "AgentCore runtime not installed. Install the optional extra: "
            'pip install -e ".[agentcore]"'
        ) from exc

    agentcore_app = BedrockAgentCoreApp()

    @agentcore_app.entrypoint
    def handler(payload: dict[str, Any]) -> dict[str, Any]:
        return invoke(payload)

    return agentcore_app


def main() -> None:  # pragma: no cover - requires the optional dependency
    build_app().run()


if __name__ == "__main__":  # pragma: no cover
    main()
