"""FastAPI application: three views, server-rendered, HTMX for actions.

Deliberately boring: one process, no build step, no client framework. The
interesting part of this project is what happens between the click and the
action, not the click.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contextlib import asynccontextmanager

from fastapi import Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import FastAPI

from app import audit, db, seed
from app.agent.providers import provider_label
from app.config import COMPANY_NAME, FACILITY_ID, REPO_ROOT, settings
from app.domain import DecisionCard, ExceptionStatus
from app.orchestrator import (
    OrchestratorError,
    activate_policy,
    approve_and_teach,
    escalate_manually,
    get_decision_card,
    handle_event,
    record_decision,
    reject_policy,
)
from app.policy import store as policy_store
from app.policy.store import ActivationDenied

BASE_DIR = Path(__file__).resolve().parent
OPERATOR = "dana.r@northgate-optics.example"

@asynccontextmanager
async def lifespan(_: FastAPI):
    if not db.db_path().exists():
        seed.seed(reset=True)
    else:
        db.init_db()
    yield


app = FastAPI(title="OneDecision", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

STATUS_ORDER = [
    ExceptionStatus.NEW,
    ExceptionStatus.INVESTIGATING,
    ExceptionStatus.WAITING_DECISION,
    ExceptionStatus.ESCALATED,
    ExceptionStatus.RESOLVED,
]

STATUS_LABELS = {
    ExceptionStatus.NEW: "New",
    ExceptionStatus.INVESTIGATING: "Investigating",
    ExceptionStatus.WAITING_DECISION: "Waiting for decision",
    ExceptionStatus.RESOLVED: "Resolved",
    ExceptionStatus.ESCALATED: "Escalated",
}


def _base_context(request: Request) -> dict[str, Any]:
    return {
        "request": request,
        "company": COMPANY_NAME,
        "facility": FACILITY_ID,
        "provider": provider_label(),
        "offline": settings.is_offline_provider,
        "operator": OPERATOR,
        "status_labels": STATUS_LABELS,
    }


def _exception_rows(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT e.*, c.sku, c.scenario_note, k.name AS kit_name
             FROM exceptions e
             JOIN return_cases c ON c.case_id = e.case_id
             JOIN kit_catalogue k ON k.sku = c.sku
            ORDER BY e.created_at DESC"""
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["escalation_reasons"] = json.loads(row["escalation_reasons"] or "[]")
        out.append(item)
    return out


def _pending_cases(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT c.case_id, c.scenario_note, k.name AS kit_name
             FROM return_cases c
             JOIN kit_catalogue k ON k.sku = c.sku
            WHERE c.is_historical = 0
              AND c.case_id NOT IN (SELECT case_id FROM exceptions)
            ORDER BY c.case_id"""
    ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------ 1. the inbox


@app.get("/", response_class=HTMLResponse)
def inbox(request: Request) -> HTMLResponse:
    with db.read_only() as conn:
        exceptions = _exception_rows(conn)
        pending = _pending_cases(conn)
        active = policy_store.list_active(conn)
    buckets = {status: [e for e in exceptions if e["status"] == status] for status in STATUS_ORDER}
    context = _base_context(request) | {
        "exceptions": exceptions,
        "buckets": buckets,
        "status_order": STATUS_ORDER,
        "pending": pending,
        "active_policies": active,
    }
    return templates.TemplateResponse(request, "inbox.html", context)


@app.post("/events/{case_id}")
def ingest_event(case_id: str):
    """Simulate a returns-dock check-in event arriving for a case."""
    result = handle_event(case_id)
    if result.status is ExceptionStatus.WAITING_DECISION:
        return RedirectResponse(f"/exceptions/{result.exception_id}", status_code=303)
    return RedirectResponse("/", status_code=303)


# ------------------------------------------------- 2. decision and replay


@app.get("/exceptions/{exception_id}", response_class=HTMLResponse)
def exception_detail(request: Request, exception_id: str) -> HTMLResponse:
    with db.read_only() as conn:
        row = conn.execute(
            """SELECT e.*, c.sku, c.scenario_note, c.inspector_notes, k.name AS kit_name
                 FROM exceptions e
                 JOIN return_cases c ON c.case_id = e.case_id
                 JOIN kit_catalogue k ON k.sku = c.sku
                WHERE e.exception_id = ?""",
            (exception_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="exception not found")

        exception = dict(row)
        exception["escalation_reasons"] = json.loads(row["escalation_reasons"] or "[]")

        found = get_decision_card(conn, exception_id)
        card: DecisionCard | None = found[1] if found else None
        decision_row = conn.execute(
            """SELECT outcome, decided_by, decided_at FROM decision_cards
                WHERE exception_id = ? ORDER BY created_at DESC LIMIT 1""",
            (exception_id,),
        ).fetchone()

        candidate = conn.execute(
            """SELECT * FROM policies WHERE origin_case_id = ?
                ORDER BY version DESC LIMIT 1""",
            (row["case_id"],),
        ).fetchone()
        candidate_record = policy_store.get(conn, candidate["policy_id"]) if candidate else None
        active = policy_store.list_active(conn)
        timeline = audit.read_for_case(conn, row["case_id"])

    context = _base_context(request) | {
        "exception": exception,
        "card": card,
        "decision": dict(decision_row) if decision_row else None,
        "candidate": candidate_record,
        "active_policies": active,
        "timeline": timeline,
    }
    return templates.TemplateResponse(request, "decision.html", context)


@app.post("/exceptions/{exception_id}/approve")
def approve(exception_id: str):
    with db.session() as conn:
        try:
            approve_and_teach(conn, exception_id, decided_by=OPERATOR)
        except OrchestratorError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/exceptions/{exception_id}", status_code=303)


@app.post("/exceptions/{exception_id}/reject")
def reject(exception_id: str, reason: str = Form("rejected by the supervisor")):
    with db.session() as conn:
        record_decision(conn, exception_id, outcome="reject", decided_by=OPERATOR)
        escalate_manually(conn, exception_id, actor=OPERATOR, reason=reason)
    return RedirectResponse(f"/exceptions/{exception_id}", status_code=303)


# --------------------------------------------------- 3. policies and audit


@app.get("/policies", response_class=HTMLResponse)
def policies(request: Request) -> HTMLResponse:
    with db.read_only() as conn:
        records = policy_store.list_all(conn)
        handled = {p.policy_id: policy_store.cases_handled(conn, p.policy_id) for p in records}
        entries = audit.read_all(conn, limit=400)
        chain = audit.verify_chain(conn)
    context = _base_context(request) | {
        "policies": records,
        "handled": handled,
        "timeline": entries,
        "chain": chain,
    }
    return templates.TemplateResponse(request, "policies.html", context)


@app.post("/policies/{policy_id}/activate")
def activate(policy_id: str, approval_token: str = Form(...)):
    """Human activation. Requires the approval token; refuses without a passing replay."""
    with db.session() as conn:
        try:
            activate_policy(
                conn, policy_id, approval_token=approval_token, activated_by=OPERATOR
            )
        except ActivationDenied as exc:
            raise HTTPException(status_code=403, detail=f"activation denied: {exc}") from exc
    return RedirectResponse("/policies", status_code=303)


@app.post("/policies/{policy_id}/reject")
def reject_candidate(policy_id: str, reason: str = Form("rejected by the supervisor")):
    with db.session() as conn:
        reject_policy(conn, policy_id, actor=OPERATOR, reason=reason)
    return RedirectResponse("/policies", status_code=303)


# ------------------------------------------------------------------ reset


@app.post("/demo/reset")
def reset_demo():
    seed.seed(reset=True)
    return RedirectResponse("/", status_code=303)


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    with db.read_only() as conn:
        chain = audit.verify_chain(conn)
    return {
        "status": "ok",
        "provider": settings.model_provider,
        "audit_chain_ok": chain.ok,
        "audit_entries": chain.entries_checked,
    }
