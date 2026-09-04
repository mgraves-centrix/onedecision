# OneDecision — Scope Lock

**Tagline:** Teach the agent once; it safely handles the next hundred.
**Track:** Professional Agents · **Hackathon:** Agents for Humans
**Scope frozen:** 2026-09-04

---

## 1. The problem

Rule-based automation handles the cases somebody already wrote down. Everything
else becomes an interruption. A returns supervisor at a small electronics
reseller is pinged twenty times a week with variations of the same question,
answers each one in thirty seconds, and never gets the time to turn that
judgment into a written policy — let alone into automation.

OneDecision closes that loop. It asks a human **once**, converts the answer into
a constrained, versioned, machine-checkable policy, proves the policy against
historical cases before anyone trusts it, and then handles matching cases
without interrupting anybody. Anything outside the approved boundary escalates.

## 2. The one exception family (MVP boundary)

**Missing-accessory exceptions discovered while checking in returned
high-value camera / electronics kits.**

Nothing else. Not refunds. Not shipping. Not other industries. Not a generic
workflow builder.

## 3. Fictional company and synthetic data

All data in this repository is invented for the demo.

| Thing | Value |
| --- | --- |
| Company | **Northgate Optics** (fictional camera and optics rental / resale) |
| Facility | `NGO-WH-1`, Returns & Inspection dock |
| Persona | Dana R., Returns Supervisor — the human who decides |
| Products | Synthetic SKUs (`NGO-KIT-*`), synthetic serials, synthetic orders |
| Customers | Synthetic names and IDs; **no real people, no PII** |

Every business system OneDecision touches is a **synthetic adapter** in
`app/adapters/` — an in-repo simulation over SQLite. They are labeled as
synthetic in the UI and in code. They are **not** production integrations, and
nothing in this project talks to a real WMS, ERP, payment system, or customer.

## 4. The golden path (the thing that must work)

```
synthetic exception event
  -> real Strands agent investigates with tools
  -> deterministic fact reconciliation
  -> no approved policy applies
  -> agent emits a typed decision card
  -> human clicks "Approve and Teach"
  -> agent proposes a constrained policy (allowlisted schema only)
  -> deterministic validation + replay against historical cases
  -> human explicitly activates the policy version
  -> next matching case resolves automatically (work order + disposition)
  -> deterministic verification of the written state
  -> append-only audit entry for every step
```

## 5. Safety architecture (non-negotiable)

The separation between *reasoning* and *acting* is the product.

1. **The model may propose. The model may never activate.** Activation is a
   human HTTP action carrying an approval token.
2. **Deterministic code decides, not the model.** The agent's investigation is
   advisory. Facts are re-derived from the adapters and reconciled against the
   agent's report; a mismatch escalates.
3. **Policies are data, not code.** A policy is a Pydantic/JSON structure with
   an allowlist of fields, operators, value types, thresholds, and actions.
   Anything off-allowlist fails validation.
4. **No generated execution.** OneDecision never executes generated Python,
   SQL, shell, or natural-language conditions. There is no `eval`.
5. **Hard invariants outrank policies.** A set of non-overridable guardrails
   (`app/policy/guardrails.py`) is evaluated before any policy. A policy can
   only ever *narrow* automation, never widen it.
6. **Replay gates activation.** A candidate policy cannot be activated until it
   has been replayed against the labeled historical case set with zero false
   automatic actions.
7. **Default to escalation.** Ambiguity, missing evidence, tool failure, model
   timeout, low confidence, or conflicting policies all escalate.
8. **Idempotency everywhere.** Every state-changing action carries an
   idempotency key; replays are no-ops that return the original result.
9. **Append-only audit.** The audit log is hash-chained and protected by SQLite
   triggers that reject `UPDATE` and `DELETE`.
10. **No hidden chain-of-thought.** The agent returns a short, structured
    rationale intended for a human reader. Raw reasoning is never surfaced or
    stored.

### Always escalate

Serial mismatch · incomplete evidence · new damage · missing or excessive
replacement cost · serialized, safety-critical, or essential missing component ·
more than one missing component · conflicting policies · tool failure ·
confidence below threshold.

## 6. Explicitly out of scope

Additional industries or exception families · real refunds, payments, email, or
third-party integrations · multi-tenancy · authentication beyond a demo
approval token · mobile app · generic workflow builder · arbitrary
natural-language automation · RAG or vector databases · multi-agent swarms ·
generated executable code · computer vision or OCR · billing, reporting, or an
analytics suite.

## 7. Architecture decisions

| # | Decision | Rationale | Reversible? |
| --- | --- | --- | --- |
| 1 | Python 3.11 + FastAPI + SQLite + Jinja2/HTMX | Zero-build, server-rendered, one process, easy for a judge to run | Yes |
| 2 | Exactly one Strands agent | The product is governance, not agent count | Yes |
| 3 | Model provider behind an adapter (`app/agent/providers/`) | AWS credentials are unavailable in the build environment; the runtime must not care which model backs it | Yes |
| 4 | A deterministic `scripted` Strands `Model` implementation | Gives hermetic tests, CI, and an offline demo while still exercising the **real** Strands agent loop and real tool calls | Yes |
| 5 | Policy DSL as a closed Pydantic schema | Makes "the model cannot widen its own authority" a type error, not a prompt instruction | Hard to reverse (core) |
| 6 | Facts re-derived deterministically, agent report reconciled | Prevents a hallucinated or injected fact from driving an action | Hard to reverse (core) |
| 7 | Hash-chained append-only audit in SQLite | Tamper-evidence without extra infrastructure | Yes |
| 8 | AgentCore compatibility kept as a thin entrypoint, not a dependency | Local golden path first, per the brief | Yes |

## 8. Assumptions

- **A1.** Judges run the project locally. `make setup && make seed && make run`
  must work with no cloud account and no credentials.
- **A2.** The AWS credentials present in the build environment are invalid for
  AWS (`sts:GetCallerIdentity` returns `InvalidClientTokenId`), so Bedrock and
  AgentCore cannot be exercised here. The Bedrock path is implemented and
  documented but is unverified against a live endpoint. See
  `docs/provenance.md`.
- **A3.** "One approved non-serialized accessory" means exactly one missing
  line item, quantity one.
- **A4.** Replacement cost is authoritative from the synthetic parts catalog,
  not from the model.
- **A5.** A single human role (returns supervisor). No user accounts; the
  approval token stands in for real authorization.
