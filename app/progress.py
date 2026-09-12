"""Live progress for the long model calls, so a page is never a dead wait.

A check-in or an approval blocks on Claude for tens of seconds. That work is one
synchronous transaction, so nothing it writes is readable by another request
until it commits: the audit log cannot feed a spinner. This module is a
deliberate side channel next to it.

It is in memory, in one process, bounded, and never read by anything that
decides, acts, or records. Losing it costs a spinner and nothing else. If the app
is ever run with more than one worker, a poll may land on a process that has no
job, and the page falls back to a plain wait.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

MAX_JOBS = 32  # bounded on purpose; one operator at a time in the demo
JOB_TTL_SECONDS = 600.0  # a job nobody collected is dropped on the next start

# What each read-only tool is actually doing, in the language of the work rather
# than the language of the function. Unknown tools fall back to their own name.
TOOL_PHRASES = {
    "get_return_case": "Reading the return case",
    "compare_expected_and_received": "Reconciling the bill of materials",
    "lookup_replacement_cost": "Pricing the missing part",
    "find_approved_policy": "Looking for a policy that already covers this",
    "replay_candidate_policy": "Dry-running the draft against past cases",
    "get_invoice": "Reading the invoice",
    "compare_invoice_to_receipt": "Reconciling the invoice against the receipt",
    "lookup_vendor_history": "Reading the vendor's history",
}


@dataclass
class _Job:
    label: str
    started: float
    seq: int = 0
    ended: float | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    done: bool = False


_lock = threading.Lock()
_jobs: dict[str, _Job] = {}
_seq = 0


def _prune(now: float) -> None:
    """Drop what is stale, then what is oldest. Caller holds the lock."""
    for key in [k for k, job in _jobs.items() if now - job.started > JOB_TTL_SECONDS]:
        del _jobs[key]
    while len(_jobs) > MAX_JOBS:
        del _jobs[min(_jobs, key=lambda k: _jobs[k].seq)]


def start(key: str, label: str, first_step: str | None = None) -> None:
    """Begin a job, replacing any previous job under the same key."""
    global _seq
    now = time.monotonic()
    with _lock:
        _seq += 1
        _jobs[key] = _Job(label=label, started=now, seq=_seq)
        if first_step:
            _jobs[key].steps.append({"text": first_step, "at": 0.0})
        # After the insert, so a burst never evicts the job just started.
        _prune(now)


def step(key: str | None, text: str) -> None:
    if not key:
        return
    with _lock:
        job = _jobs.get(key)
        if job is None or job.done:
            return
        if job.steps and job.steps[-1]["text"] == text:
            return
        job.steps.append({"text": text, "at": round(time.monotonic() - job.started, 1)})


def tool_called(key: str | None, name: str, *, ok: bool, summary: str = "") -> None:
    """A tool call, phrased as the work it did rather than the function it is."""
    phrase = TOOL_PHRASES.get(name, name.replace("_", " "))
    step(key, phrase if ok else f"{phrase} — failed")


def finish(key: str | None) -> None:
    if not key:
        return
    with _lock:
        job = _jobs.get(key)
        if job is not None and not job.done:
            job.done = True
            job.ended = time.monotonic()


def read(key: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(key)
        if job is None:
            return None
        return {
            "label": job.label,
            # Frozen once the run is over, so a finished panel stops counting.
            "elapsed": round((job.ended or time.monotonic()) - job.started, 1),
            "done": job.done,
            "steps": list(job.steps),
        }


def clear() -> None:
    """Drop every job. For tests, and for the demo reset."""
    with _lock:
        _jobs.clear()
