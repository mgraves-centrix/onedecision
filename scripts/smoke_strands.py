#!/usr/bin/env python3
"""Minimal Strands smoke test.

Proves three things before anything else is built on top of them:
  1. a real Strands `Agent` runs against the configured model provider,
  2. it makes visible tool calls, and
  3. it returns typed structured output.

Run: python scripts/smoke_strands.py
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, seed  # noqa: E402
from app.agent.build import investigation_agent  # noqa: E402
from app.agent.providers import provider_label  # noqa: E402
from app.agent.tools import AgentContext  # noqa: E402
from app.config import settings  # noqa: E402
from app.domain import InvestigationReport  # noqa: E402

CASE_ID = "CASE-2001"


def main() -> int:
    if not db.db_path().exists():
        seed.seed(reset=True)

    print(f"provider : {provider_label()}")
    print(f"database : {db.db_path()}")
    print(f"case     : {CASE_ID}\n")

    with db.session() as conn:
        ctx = AgentContext(conn=conn, trace_id=f"trc_{uuid.uuid4().hex[:12]}", case_id=CASE_ID)

        if settings.is_offline_provider:
            from app.agent.providers.scripted import set_scripted_context

            set_scripted_context(case_id=CASE_ID)

        agent = investigation_agent(ctx)
        result = agent(
            f"Investigate return case {CASE_ID} and report what you found.",
            structured_output_model=InvestigationReport,
        )

        report = result.structured_output
        print("tool calls made by the agent:")
        for call in ctx.calls:
            flag = "ok  " if call.ok else "FAIL"
            print(f"  [{flag}] {call.name}({call.arguments}) -> {call.summary}")

        print(f"\nstop reason        : {result.stop_reason}")
        print(f"structured output  : {type(report).__name__}")
        if isinstance(report, InvestigationReport):
            print(f"  missing components : {report.observed_missing_component_count}")
            print(f"  serial match       : {report.observed_serial_match}")
            print(f"  replacement cost   : {report.observed_replacement_cost_usd}")
            print(f"  matching policy    : {report.matching_policy_id}")
            print(f"  recommendation     : {report.recommended_action}")
            print(f"  confidence         : {report.confidence}")
            print(f"  rationale          : {report.rationale}")
            print("\nSMOKE TEST PASSED")
            return 0

    print("\nSMOKE TEST FAILED: no typed structured output returned")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
