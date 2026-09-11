"""Operations dashboard: what the agent handled, what people decided, and what it
took to run.

Every number is counted from records the product already writes: the
`exceptions` table, the policy store, `decision_cards`, and the hash-chained audit
log. Usage comes from the audit log's `tool.*` events and the `agent.run` event
recorded after each agent invocation. Nothing is estimated: token counts appear
only when the model provider reported them.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from app import audit
from app.audit import AuditEventType

if TYPE_CHECKING:
    from app.db import Connection

RANGES: dict[str, tuple[str, timedelta | None]] = {
    "all": ("All time", None),
    "24h": ("Last 24 hours", timedelta(hours=24)),
    "7d": ("Last 7 days", timedelta(days=7)),
    "30d": ("Last 30 days", timedelta(days=30)),
}
DEFAULT_RANGE = "all"

STEP_LABELS = {
    "investigation": "Investigation",
    "decision_card": "Decision card",
    "policy_proposal": "Policy proposal",
}

DECISION_LABELS = {
    "approve_and_teach": "Approved and taught",
    "reject": "Rejected",
}

# (bucket, label, pill class). The pill carries the status color and its label
# together, so outcome is never shown by color alone; the bars stay one hue.
_OUTCOMES = [
    ("automated", "Handled automatically", "status-resolved"),
    ("waiting", "Waiting for a decision", "status-waiting_decision"),
    ("escalated", "Escalated to a person", "status-escalated"),
    ("resolved_other", "Resolved without a policy", ""),
    ("in_progress", "In progress", ""),
]

_USAGE_EVENTS = (
    AuditEventType.AGENT_RUN,
    AuditEventType.TOOL_CALLED,
    AuditEventType.TOOL_FAILED,
    AuditEventType.INVESTIGATION_STARTED,
    AuditEventType.ACTION_EXECUTED,
    AuditEventType.ACTION_DUPLICATE,
    AuditEventType.ACTION_FAILED,
    AuditEventType.VERIFICATION_PASSED,
    AuditEventType.VERIFICATION_FAILED,
    AuditEventType.POLICY_ACTIVATED,
)

# Column chart geometry, in SVG user units. Columns are capped at 24 wide and
# take 60% of their slot, so the rest of the slot is air.
_CHART_WIDTH = 720
_CHART_LEFT = 36
_CHART_RIGHT = 24  # room for the last date label, centered on the last column
_CHART_TOP = 12
_CHART_PLOT = 140
_CHART_AXIS = 26
_MAX_COLUMN = 24.0


def resolve_range(key: str | None) -> str:
    return key if key in RANGES else DEFAULT_RANGE


def compact(n: int) -> str:
    """Stat-tile formatting: 1,284 / 12.9K / 4.2M."""
    if n < 10_000:
        return f"{n:,}"
    if n < 1_000_000:
        return f"{n / 1000:.1f}".rstrip("0").rstrip(".") + "K"
    return f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"


def seconds(ms: float | None) -> str:
    """Durations: "850 ms" below a second, "1.4 s" from a second up."""
    if ms is None:
        return "—"
    return f"{ms:.0f} ms" if ms < 1000 else f"{ms / 1000:.1f} s"


def build_dashboard(
    conn: "Connection", range_key: str | None = DEFAULT_RANGE, *, now: datetime | None = None
) -> dict[str, Any]:
    """Everything the dashboard shows, scoped to one time range."""
    now = now or datetime.now(timezone.utc)
    key = resolve_range(range_key)
    label, delta = RANGES[key]
    cutoff = (now - delta).isoformat(timespec="milliseconds") if delta else None

    cases = _cases(conn, cutoff)
    events = _events(conn, cutoff)
    return {
        "range_key": key,
        "range_label": label,
        "ranges": [(k, v[0]) for k, v in RANGES.items()],
        "cases": _case_summary(cases),
        "outcomes": _outcome_bars(cases),
        "activity": _activity(cases, key, now),
        "recent_cases": cases[:15],
        "decisions": _decisions(conn, cutoff),
        "policies": _policies(conn),
        "operations": _operations(events),
        "usage": _usage(events),
        "chain": audit.verify_chain(conn),
        "recent_events": audit.read_recent(conn, limit=25, since=cutoff),
    }


# ----------------------------------------------------------------- history


def _cases(conn: "Connection", cutoff: str | None) -> list[dict[str, Any]]:
    sql = """SELECT e.exception_id, e.case_id, e.status, e.applied_policy_id,
                    e.created_at, e.updated_at, k.name AS kit_name
               FROM exceptions e
               JOIN return_cases c ON c.case_id = e.case_id
               JOIN kit_catalog k ON k.sku = c.sku"""
    params: tuple[Any, ...] = ()
    if cutoff:
        sql += " WHERE e.created_at >= ?"
        params = (cutoff,)
    sql += " ORDER BY e.created_at DESC"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _bucket(case: dict[str, Any]) -> str:
    status = case["status"]
    if status == "resolved":
        return "automated" if case["applied_policy_id"] else "resolved_other"
    if status == "waiting_decision":
        return "waiting"
    if status == "escalated":
        return "escalated"
    return "in_progress"


def _case_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(_bucket(c) for c in cases)
    total = len(cases)
    return {
        "total": total,
        "automated": counts["automated"],
        "waiting": counts["waiting"],
        "escalated": counts["escalated"],
        "resolved_other": counts["resolved_other"],
        "in_progress": counts["in_progress"],
        "automated_pct": round(counts["automated"] / total * 100) if total else None,
    }


def _outcome_bars(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(_bucket(c) for c in cases)
    peak = max(counts.values(), default=0)
    rows = []
    for key, label, pill in _OUTCOMES:
        n = counts[key]
        if n == 0 and key in ("resolved_other", "in_progress"):
            continue
        rows.append({"label": label, "pill": pill, "count": n, "pct": n / peak * 100 if peak else 0})
    return rows


def _decisions(conn: "Connection", cutoff: str | None) -> list[dict[str, Any]]:
    sql = "SELECT outcome, COUNT(*) AS c FROM decision_cards WHERE decided_at IS NOT NULL"
    params: tuple[Any, ...] = ()
    if cutoff:
        sql += " AND decided_at >= ?"
        params = (cutoff,)
    sql += " GROUP BY outcome"
    counts = {r["outcome"]: int(r["c"]) for r in conn.execute(sql, params).fetchall()}
    return [
        {"label": DECISION_LABELS.get(outcome, outcome), "count": counts[outcome]}
        for outcome in sorted(counts)
    ]


def _policies(conn: "Connection") -> dict[str, Any]:
    rows = conn.execute("SELECT status, COUNT(*) AS c FROM policies GROUP BY status").fetchall()
    active = conn.execute(
        "SELECT family, version FROM policies WHERE status = ? ORDER BY family, version",
        ("active",),
    ).fetchall()
    return {
        "by_status": {r["status"]: int(r["c"]) for r in rows},
        "active": [f"{r['family']}@v{r['version']}" for r in active],
    }


def _activity(cases: list[dict[str, Any]], key: str, now: datetime) -> dict[str, Any]:
    """Cases received per hour (last 24 hours) or per day (7 or 30 days), in UTC."""
    if key == "24h":
        slots, step = 24, timedelta(hours=1)
        end = now.replace(minute=0, second=0, microsecond=0) + step
        tick_fmt, period_fmt = "%H:00", "%b %d, %H:00 UTC"
        caption = "Cases received per hour, last 24 hours (UTC)"
    else:
        slots, step = (7 if key == "7d" else 30), timedelta(days=1)
        end = now.replace(hour=0, minute=0, second=0, microsecond=0) + step
        tick_fmt, period_fmt = "%b %d", "%b %d"
        caption = f"Cases received per day, last {slots} days (UTC)"

    first = end - step * slots
    counts = [0] * slots
    for case in cases:
        at = datetime.fromisoformat(case["created_at"])
        if first <= at < end:
            counts[int((at - first) / step)] += 1
    starts = [first + step * i for i in range(slots)]
    return _column_chart(starts, counts, tick_fmt, period_fmt) | {"caption": caption}


def _column_chart(
    starts: list[datetime], counts: list[int], tick_fmt: str, period_fmt: str
) -> dict[str, Any]:
    n = len(counts)
    slot = (_CHART_WIDTH - _CHART_LEFT - _CHART_RIGHT) / n
    width = min(_MAX_COLUMN, slot * 0.6)
    peak = max(counts, default=0)
    base = _CHART_TOP + _CHART_PLOT
    tick_every = max(1, math.ceil(n / 7))
    columns = []
    for i, (start, count) in enumerate(zip(starts, counts)):
        slot_x = _CHART_LEFT + i * slot
        x = slot_x + (slot - width) / 2
        top = base - (count / peak * _CHART_PLOT if peak else 0.0)
        period = start.strftime(period_fmt)
        columns.append(
            {
                "slot_x": round(slot_x, 2),
                "slot_w": round(slot, 2),
                "center": round(slot_x + slot / 2, 2),
                "path": _column_path(x, top, width, base) if count else "",
                "count": count,
                "period": period,
                "tip": f"{period}: {count} case{'' if count == 1 else 's'}",
                "tick": start.strftime(tick_fmt) if i % tick_every == 0 or i == n - 1 else "",
            }
        )
    return {
        "width": _CHART_WIDTH,
        "height": base + _CHART_AXIS,
        "left": _CHART_LEFT,
        "right": _CHART_WIDTH - _CHART_RIGHT,
        "top": _CHART_TOP,
        "base": base,
        "peak": peak,
        "columns": columns,
    }


def _column_path(x: float, top: float, width: float, base: float) -> str:
    """A column with a 4px rounded data end and a square foot on the baseline."""
    r = min(4.0, width / 2, base - top)
    return (
        f"M{x:.2f},{base:.2f} V{top + r:.2f} Q{x:.2f},{top:.2f} {x + r:.2f},{top:.2f} "
        f"H{x + width - r:.2f} Q{x + width:.2f},{top:.2f} {x + width:.2f},{top + r:.2f} "
        f"V{base:.2f} Z"
    )


# ------------------------------------------------------------------- usage


def _events(conn: "Connection", cutoff: str | None) -> list[tuple[str, dict[str, Any]]]:
    placeholders = ", ".join("?" for _ in _USAGE_EVENTS)
    sql = f"SELECT event_type, payload FROM audit_log WHERE event_type IN ({placeholders})"
    params: list[Any] = list(_USAGE_EVENTS)
    if cutoff:
        sql += " AND created_at >= ?"
        params.append(cutoff)
    return [
        (r["event_type"], json.loads(r["payload"]))
        for r in conn.execute(sql, tuple(params)).fetchall()
    ]


def _operations(events: list[tuple[str, dict[str, Any]]]) -> dict[str, int]:
    counts = Counter(event_type for event_type, _ in events)
    return {
        "actions_executed": counts[AuditEventType.ACTION_EXECUTED],
        "duplicates_suppressed": counts[AuditEventType.ACTION_DUPLICATE],
        "actions_failed": counts[AuditEventType.ACTION_FAILED],
        "verified": counts[AuditEventType.VERIFICATION_PASSED],
        "verification_failed": counts[AuditEventType.VERIFICATION_FAILED],
        "activations": counts[AuditEventType.POLICY_ACTIVATED],
    }


def _usage(events: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    tools: dict[str, dict[str, int]] = {}
    runs: list[dict[str, Any]] = []
    investigations = 0
    for event_type, payload in events:
        if event_type in (AuditEventType.TOOL_CALLED, AuditEventType.TOOL_FAILED):
            # A failed agent step is recorded as tool.failed with a step, not a tool.
            name = payload.get("tool") or f"{payload.get('step', 'agent')} step"
            row = tools.setdefault(name, {"calls": 0, "failed": 0})
            row["calls"] += 1
            row["failed"] += event_type == AuditEventType.TOOL_FAILED
        elif event_type == AuditEventType.AGENT_RUN:
            runs.append(payload)
        elif event_type == AuditEventType.INVESTIGATION_STARTED:
            investigations += 1

    peak = max((t["calls"] for t in tools.values()), default=0)
    tool_rows = [
        {"name": name, **row, "pct": row["calls"] / peak * 100 if peak else 0}
        for name, row in sorted(tools.items(), key=lambda item: (-item[1]["calls"], item[0]))
    ]

    def total(field: str, rows: list[dict[str, Any]]) -> int:
        return sum(int(r.get(field) or 0) for r in rows)

    by_step: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        by_step[run.get("step", "unknown")].append(run)
    steps = []
    for step in [*STEP_LABELS, *sorted(set(by_step) - set(STEP_LABELS))]:
        rows = by_step.get(step)
        if not rows:
            continue
        step_tokens = total("total_tokens", rows)
        steps.append(
            {
                "label": STEP_LABELS.get(step, step),
                "runs": len(rows),
                "avg_duration": seconds(total("duration_ms", rows) / len(rows)),
                "avg_latency": seconds(total("model_latency_ms", rows) / len(rows)),
                "tokens": compact(step_tokens) if step_tokens else "—",
            }
        )

    tokens = {
        "input": total("input_tokens", runs),
        "output": total("output_tokens", runs),
        "total": total("total_tokens", runs),
    }
    providers = Counter(str(r.get("provider", "unknown")) for r in runs)
    return {
        "agent_runs": len(runs),
        "investigations": investigations,
        "tool_calls": sum(t["calls"] for t in tools.values()),
        "tool_failures": sum(t["failed"] for t in tools.values()),
        "tools": tool_rows,
        "tokens": tokens
        | {"input_display": compact(tokens["input"]), "output_display": compact(tokens["output"])},
        "tokens_reported": tokens["total"] > 0,
        "tokens_display": compact(tokens["total"]),
        "avg_duration": seconds(total("duration_ms", runs) / len(runs)) if runs else "—",
        "steps": steps,
        "providers": [{"label": label, "runs": n} for label, n in providers.most_common()],
    }
