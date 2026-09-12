# OneDecision

**Teach the agent once; it safely handles the next hundred.**

Built for **Agents for Humans** · Professional Agents track · Strands Agents on Claude Opus 5, deployed to Amazon Bedrock AgentCore Runtime

![OneDecision architecture](docs/architecture.png)

Hover any component in [the interactive architecture](docs/architecture.html) to see what it
connects to and which way the data moves. Both views render from `docs/architecture.json`.

---

## The problem

Rule-based automation handles the cases someone already wrote down. Everything else
becomes an interruption.

A returns supervisor at a small electronics reseller gets pinged twenty times a week
with variations of the same question — *a kit came back missing its lens cap, what do I
do?* — answers each one in thirty seconds, and never gets the hour it would take to
turn that judgment into a written policy, let alone into automation. The knowledge stays
in their head. The interruptions keep coming.

## What OneDecision does

It closes that loop, once:

1. An unfamiliar exception arrives **as an event**, not a chat prompt.
2. A Strands agent investigates it with tools and reconciles the evidence.
3. No approved policy covers it, so the agent produces **one compact decision card** —
   evidence, recommendation, what it is unsure about, and the boundaries it thinks the
   decision should live inside.
4. The supervisor clicks **Approve and Teach**.
5. The agent proposes a **tightly bounded, schema-validated policy**. It is inert.
6. Deterministic code **replays** the candidate against 24 labeled historical cases.
7. A **policy diff** shows exactly what changes, and flags anything that gets
   *wider*. The supervisor can **revise** the boundary — tighten the spend cap,
   raise the confidence floor, restrict it to one kit category — which creates a
   new candidate that is replayed again from scratch.
8. The supervisor **explicitly activates** the version.
8. The next matching case resolves automatically — work order raised, disposition set,
   writes verified, exception closed against the policy version.
9. A risky near-match still escalates.
10. Every step is in an append-only, hash-chained audit log.

This is not an agent that writes SOPs. It converts recurring human judgment into
governed, testable automation — and it can prove what that automation would have done
before anyone trusts it.

---

## Quick start (no AWS account, no credentials, no network)

```bash
make setup     # venv + pinned dependencies
make seed      # build the demo database from the synthetic fixtures
make run       # http://127.0.0.1:8000
```

Then, in the app: check in **CASE-2001** → *Approve and teach* → activate the policy →
check in **CASE-2002** (resolves itself) → check in **CASE-2003** (escalates).

The **Dashboard** tab shows the history and usage behind it: cases by outcome, the share
handled automatically, human decisions and policy activations, agent runs, tool calls by
tool, and model tokens when the provider reports them. Every number is counted from the
cases table, the policy store, and the audit log.

Activating a policy asks for an approval token, because a human authorizing
automation is the whole point. On a fresh clone that token is:

```
replace-me-local-demo-token
```

It is a placeholder, not a secret, and the activation screen prints it for you.
Set `ONEDECISION_APPROVAL_TOKEN` to replace it — the on-screen notice disappears
when you do.

No account, no sign-up, no cloud, no credentials, no spend: the whole product
runs on one machine from a fresh clone.

### On PostgreSQL, the deployment target

```bash
make db-up     # docker compose PostgreSQL + migrations + seed
make test-pg   # the whole suite against BOTH backends
make run
```

If 5432 is already taken on your machine, publish the container somewhere else and
everything follows, including both connection strings:

```bash
ONEDECISION_PG_PORT=55432 make db-up
ONEDECISION_PG_PORT=55432 make test-pg
```

Or point at any PostgreSQL and the app follows:

```bash
export ONEDECISION_DATABASE_URL=postgresql://user:pass@host:5432/onedecision
make migrate && make seed && make run
```

Or watch the whole thing in the terminal:

```bash
make demo      # the golden path, start to finish
make test      # 199 hermetic tests across both domains, a few seconds
make eval      # evaluation harness -> docs/evaluation-results.md
make smoke     # minimal Strands agent + real tool calls + typed output
```

`make seed` is also the **Reset Demo** button in the UI.

---

## Is the agent real?

Yes. `make smoke` prints it:

```
tool calls made by the agent:
  [ok  ] get_return_case({'case_id': 'CASE-2001'}) -> Meridian 4100 Mirrorless Body Kit ...
  [ok  ] compare_expected_and_received({'case_id': 'CASE-2001'}) -> 1 missing, serial matches ...
  [ok  ] lookup_replacement_cost({'component_id': 'CMP-STRAP-NEO'}) -> CMP-STRAP-NEO: $14.00
  [ok  ] find_approved_policy({'case_id': 'CASE-2001'}) -> no active policies exist ...
structured output  : InvestigationReport
```

One `strands.Agent`, real `@tool` functions, real tool calls, typed Pydantic structured
output. The **model provider** behind it is swappable:

| `ONEDECISION_MODEL_PROVIDER` | What it is | Needs |
| --- | --- | --- |
| `scripted` (default) | A deterministic implementation of the Strands `Model` interface, in `app/agent/providers/scripted.py` | nothing |
| `bedrock` | Strands `BedrockModel` | AWS credentials + Bedrock model access |
| `anthropic` | Strands `AnthropicModel` | `ANTHROPIC_API_KEY` |

The `scripted` provider exists so that tests, CI, and a judge with no AWS account all
exercise the **real** Strands agent loop with **zero** credentials and zero spend. It is
not a bypass: it produces proposals like any other model, and every proposal goes
through the same schema validation, guardrails, replay, and human activation gate.

**Hosted-model status:** both hosted providers pass `make smoke` against the live service
with Claude Opus 5: the Anthropic API (`claude-opus-5`) and Amazon Bedrock
(`us.anthropic.claude-opus-5`, the cross-Region inference profile). The first Bedrock run
exposed a concurrency bug: the model requested several tools in one turn, Strands ran them
concurrently, and they collided on the shared database connection. The agent escalated
rather than act on the bad data, and tools now run one at a time, with a regression test.
The opt-in integration tests (real tool calls, a report that reconciles with the source
systems, and a schema-valid policy proposal) pass against Bedrock, 3 of 3. They have not
been run against the Anthropic API.

**AgentCore Runtime status:** deployed to AgentCore Runtime in `us-west-2` with the
AgentCore CLI, and invoked live: the deployed agent investigates CASE-2001 on Bedrock
with four real tool calls and returns a decision card. Each runtime session seeds its own
SQLite database, so taught policies do not carry across sessions; the full teach-once loop
runs in the local app. See [docs/deployment-agentcore.md](docs/deployment-agentcore.md).

---

## The safety architecture

The separation between *reasoning* and *acting* is the product.

| # | Guarantee | Where it lives |
| --- | --- | --- |
| 1 | The model may propose. It may **never** activate. | `app/policy/store.py::activate` |
| 2 | Deterministic code decides, not the model. Facts are re-derived from the systems and the agent's report is reconciled against them; a disagreement escalates. | `app/facts.py` |
| 3 | Policies are **data**, not code — allowlisted fields, operators, value types, thresholds and actions. | `app/policy/schema.py` |
| 4 | No generated Python, SQL, shell, or natural-language conditions. No `eval` anywhere. | `app/policy/engine.py` |
| 5 | Hard invariants outrank policies. A policy can only ever *narrow* automation. | `app/policy/guardrails.py` |
| 6 | Replay gates activation: one false automatic action blocks it outright — for a human revision exactly as for an agent proposal. | `app/policy/replay.py` |
| 6b | A revision can tighten or loosen a boundary within the guardrails, but has no way to remove a safety condition or add an action. | `app/policy/proposal.py` |
| 7 | Default to escalation on anything ambiguous. | throughout |
| 8 | Every state-changing action carries an idempotency key. | `app/adapters/warehouse.py` |
| 9 | Append-only, hash-chained audit log; `UPDATE`/`DELETE` rejected by database triggers, and by `REVOKE` on PostgreSQL. | `app/audit.py`, `app/db/` |
| 10 | No hidden chain-of-thought is surfaced or stored. | `app/agent/prompts.py` |

**The agent has no state-changing tools at all.** Every tool in `app/agent/tools.py` is
read-only. `execute_approved_policy`, `verify_action`, and policy activation are ordinary
Python functions in `app/orchestrator.py` and `app/policy/store.py` that the model has no
way to call.

### Always escalates

Serial mismatch · incomplete evidence · new damage · missing or excessive replacement
cost · serialized, safety-critical, or essential missing component · more than one
missing component · conflicting policies · tool failure · confidence below threshold ·
any disagreement between the agent's report and the source systems.

---

## Measured results

From `make eval` — counted from the database after a real run, not estimated. Full
report: [docs/evaluation-results.md](docs/evaluation-results.md).

| Metric | Result | Target |
| --- | --- | --- |
| Cases evaluated | 24 fixed synthetic cases | — |
| Task-completion rate | 100.0% | high |
| Correct auto-resolution rate | 100.0% | high |
| Correct-escalation rate | 100.0% | 100% |
| **False automatic actions** | **0** | **0** |
| **Prohibited actions** | **0** | **0** |
| **Duplicate actions** | **0** | **0** |
| Average end-to-end workflow | ~15 ms | — |

The number that matters is **false automatic actions**: cases the system acted on by
itself that a person should have seen. Zero is a design constraint, not an average.

---

## Beyond returns

The subject is returns because a demo needs one. The machinery underneath does not know
what a camera is: roughly 60% of `app/` is domain-neutral, and everything that *is*
domain-specific lives in one pack under `app/domains/`.

A pack supplies six things and nothing else:

1. the fact record a policy may test, and how those facts are derived,
2. the non-overridable guardrails,
3. the fixed action set, with its caps,
4. an executor for those actions and a read-back verifier,
5. a labeled historical corpus to replay against,
6. the hard ceilings no policy may exceed.

**A second domain ships in this repository.** `ap.invoice_variance` governs an
accounts-payable exception: an invoice that does not match its purchase order. Its facts,
guardrails, actions and systems of record have nothing in common with returns.

| | Returns | Accounts payable |
| --- | --- | --- |
| Family | `returns.missing_accessory` | `ap.invoice_variance` |
| The recurring question | *a kit came back missing its lens cap, what do I do?* | *the invoice is $42 over the PO, do I pay it?* |
| Fields a policy may test | 9 | 9 |
| Hard ceilings | $50 replacement, 1 component | $250 variance, 5% of the PO |
| Fixed actions | hold for parts, raise a replacement work order, close | post a variance adjustment, release for payment, close |
| Guardrails | serial mismatch, new damage, safety-critical or essential part, incomplete evidence | duplicate invoice, vendor on hold, no PO, receipt mismatch, tax mismatch, missing approver |
| Labeled corpus | 24 return cases | 24 invoices |
| Replay of the taught policy | 11 automated, 13 escalated, **0 wrong** | 12 automated, 12 escalated, **0 wrong** |

What the second domain reuses **without changing a line of it**: the constrained policy
language, the deterministic engine, the replay gate, the activation gate and its token,
idempotent execution, read-back verification, the hash-chained audit log, the policy diff,
and both database backends. Adding it *removed* 73 lines from the orchestrator, because
returns-specific dispatch became a domain's own business.

`tests/test_domain_ap_invoices.py` is the evidence: 17 tests that touch no returns code and
needed no change to the governance code. They cover fact derivation from the ledger, every
guardrail boundary, a policy language that refuses a field from another domain and an
adjustment cap above its own condition, a replay that scores 24 labeled invoices, an
activation refused without a passing replay and without a token, execution that pays once
when run twice, verification that reads the ledger back, and the audit chain intact.

**What a new domain costs:** about 480 lines of Python (a fact record and its derivation, the
guardrails, the action set, an executor and verifier, a synthetic adapter), plus its
fixtures, its labeled corpus and its tests.

**What it does not include yet, honestly:** the web app's screens and the agent's tools and
prompts are still returns-shaped, so the AP domain is exercised through the governance path
and its tests rather than through the agent loop and the UI. Making a domain first-class in
the interface is UI work on top of the seam, not another rewrite of the machinery.

**Where this design refuses to go:** a domain has to reduce its judgment to allowlisted
fields. Where the decision genuinely turns on free-text nuance that cannot be derived
deterministically, there is nothing to replay and nothing to bound — and this system will
not automate it. That is a constraint by construction, not an omission.

---

## The synthetic world

Everything is invented. The company is **Northgate Optics**, a fictional camera and
optics rental/resale business. All SKUs, serials, orders, customer references, inspection
notes, and warehouse records are fabricated for this demo, and every "business system"
is a labeled synthetic adapter in `app/adapters/` backed by local SQLite.

**No real customer data, no PII, no private SOPs, no credentials, and no production
integrations anywhere in this repository.** The UI says so on every page.

---

## Layout

```
app/
  agent/           the one Strands agent: tools, prompts, model providers
    providers/     bedrock | anthropic | scripted (deterministic Model impl)
    tools.py       READ-ONLY tools. Nothing here writes.
  adapters/        SYNTHETIC business systems (returns, parts, warehouse, AP ledger)
  domains/         domain packs: facts, guardrails, actions, corpus
    returns.py     the returns domain
    ap_invoices.py a second domain on the same machinery
  policy/
    schema.py      the allowlist: fields, operators, values, actions
    diff.py        policy-version diff, classified narrower / wider
    guardrails.py  non-overridable invariants
    engine.py      deterministic evaluation, no dynamic execution
    replay.py      the replay gate
    store.py       persistence + THE ACTIVATION GATE
  orchestrator.py  the golden path; the only code that acts
  facts.py         deterministic facts + reconciliation
  audit.py         append-only, hash-chained
  evaluation.py    the measurement harness
  main.py          FastAPI: inbox / decision+replay / policies+audit / dashboard
  dashboard.py     history and usage, counted from case records and the audit log
  agentcore.py     AgentCore Runtime handler, deployed through agentcore_main.py
  db/
    postgres_backend.py  deployment target: pooling, advisory lock, NUMERIC
    sqlite_backend.py    zero-setup demo backend
    migrations/          versioned SQL, one file per dialect
fixtures/          synthetic catalog + 24 historical + 6 demo cases
tests/             hermetic; every test runs on both backends
docs/              scope, architecture, database, evaluation, demo, provenance
agentcore/         AgentCore CLI project: runtime config and CDK app
agentcore_main.py  AgentCore Runtime entrypoint (imports app.agentcore)
tools/video/       draft demo video: a live take in Chrome, Polly voiceover, assembly
```

## Database

**PostgreSQL is the deployment target. SQLite is a labeled zero-setup demo
backend**, kept so the product runs from a fresh clone with no server. One
environment variable switches between them, and **the entire suite runs against
both** — so they cannot drift.

Porting off SQLite surfaced three defects that were only invisible because
SQLite has a single writer:

1. **The audit hash chain could fork.** Appending is read-head-then-insert, a
   race with concurrent writers. Fixed with a transaction-scoped advisory lock,
   plus `UNIQUE(prev_hash)` as a backstop. Remove the lock and
   `test_concurrent_audit_appends_keep_the_chain_intact` fails immediately with
   a duplicate-key violation on the forked head — the test has teeth.
2. **Event de-duplication was select-then-insert.** Two copies of one warehouse
   event both passed the check. Now `ON CONFLICT (event_key) DO NOTHING
   RETURNING`, so the database decides the race and the loser is a no-op.
3. **Money was floating point.** `REAL` gating an authorized spend cap is a
   latent rounding bug. Now `NUMERIC(12,2)`, coerced at the adapter boundary.

Full write-up, including what still stands between this and production:
[docs/database.md](docs/database.md).

## Configuration

Copy `.env.example` to `.env` and edit it — the app reads it on startup. Everything has
a safe local default; nothing is required to run the demo.

A real environment variable always beats the file, so a deployment cannot be overridden
by a stray `.env` on disk. `.env` is gitignored and a test asserts it stays that way.
**Never commit a real `.env`** — it is where an API key goes.

## Tests

```bash
make test        # hermetic. No network, no model calls. SQLite, plus PostgreSQL if it is up.
make test-pg     # the whole suite against BOTH backends (401 runs)
pytest -m integration    # opt-in, needs a live model provider
```

Coverage includes: policy-schema validation, allowlisted fields/operators/actions,
default escalation, approval and policy-version checks, threshold boundaries,
conflicting policies, replay gating, action idempotency, duplicate events, append-only
audit behavior and tamper detection, malformed and incomplete evidence, prompt
injection inside case notes, model timeout and tool failure, unknown case → decision
card, approval → candidate without activation, failed replay blocking activation,
explicit activation after successful replay, later matching case completing
automatically, and a risky near-match escalating — plus, on PostgreSQL,
concurrent audit appends, concurrent duplicate events, and concurrent
idempotency-key collisions.

## License

Apache-2.0. See [LICENSE](LICENSE).
