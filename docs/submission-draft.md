# Devpost submission draft

> Draft copy for the Devpost form. Nothing here has been submitted. Fields marked
> **[OWNER]** need information or authorization only the submitter can supply.

---

## Project name

**OneDecision**

## Elevator pitch (200 characters)

> Teach the agent once; it safely handles the next hundred. OneDecision turns one
> approved human judgment call into a replay-tested, human-activated policy, and
> escalates everything outside it.

*(192 characters)*

## Track

Professional Agents

---

## Inspiration

Automation handles the cases someone already wrote down. Everything else becomes an
interruption.

Talk to anyone running operations at a small company and you find the same shape: a
person who gets asked the same *kind* of question twenty times a week, answers it in
thirty seconds, and never gets the hour it would take to turn that judgment into a
written policy, let alone into automation. The knowledge stays in their head. The
interruptions keep coming. And the moment you suggest automating it, the honest objection
lands: *how would I know it isn't going to do something stupid on the one case that's
different?*

That objection is the real product requirement. Not "can an agent do this", but "can a
person hand over judgment and still be able to sleep".

## What it does

OneDecision watches one narrow class of exception (a returned high-value camera kit that
came back missing an accessory) and closes the learning loop exactly once.

1. An exception arrives **as an event**, not as a chat prompt.
2. A Strands agent investigates with tools: pulls the case, reconciles the bill of
   materials against what physically arrived, prices the missing part, and checks for an
   approved policy.
3. No policy covers it, so it produces **one compact decision card**: the evidence and
   the tool that produced each line, a recommendation, what it is genuinely unsure about,
   the **boundaries** the decision should live inside, and why a person has to decide.
4. The supervisor clicks **Approve and Teach**.
5. The agent proposes a **tightly bounded policy** in a constrained language. It is inert.
6. Deterministic code **replays** the candidate against 24 labeled historical cases and
   reports exactly what it would have automated, escalated, and got wrong.
7. The supervisor **explicitly activates** the version.
8. The next matching case resolves by itself: work order raised, disposition set, both
   writes read back and verified, exception closed against the policy version.
9. A case that looks almost identical but has a serial mismatch **still escalates**.
10. Every step is in an append-only, hash-chained audit log.
11. A dashboard shows the history and usage behind it: outcomes, the share handled
    automatically, human decisions, agent runs, tool calls by tool, and model tokens
    when the provider reports them, all counted from the product's own records.

## How we built it

**Python 3.11 · Strands Agents SDK · FastAPI · Pydantic · PostgreSQL, with SQLite as the
zero-setup demo backend · server-rendered HTML.** One process, no build step, no client
framework.

There is exactly **one** Strands agent. It is invoked three times along the path:
investigate, produce the decision card, propose the policy, each with the same tools and a
task-specific prompt each time. Extra agents would have added moving parts, not
capability.

The interesting engineering is the line between reasoning and acting:

- **The agent has no state-changing tools at all.** Every tool is read-only.
  `execute_approved_policy`, `verify_action`, and policy activation are ordinary Python
  functions the model has no way to call.
- **Policies are data, not code.** A policy is a Pydantic structure with an allowlist of
  nine fields, eight operators, typed values, hard numeric ceilings, and three fixed
  actions. There is no `eval`, no generated SQL, no generated Python, and no
  natural-language condition anywhere.
- **The agent doesn't even choose the actions.** The proposal schema has no field into
  which a model could write "issue a refund". The action set is assembled from the
  allowlist server-side. That whole class of failure is a missing field, not a check.
- **Facts come from the systems, not the model.** The agent's report is reconciled
  against independently derived facts; any disagreement escalates. A hallucination, or a
  prompt injection buried in an inspector's note, can only make the system *more*
  conservative.
- **Hard guardrails outrank policies** and run before any policy is consulted. A policy
  can only ever narrow automation.
- **Replay gates activation.** One false automatic action against history blocks it.
- **A human can revise the boundary, and the diff says which way it moved.** The
  supervisor can tighten the agent's proposal or loosen it within the guardrails;
  the diff labels every change narrower or wider, and a revision is replayed from
  scratch before it can be activated. Building this surfaced a real flaw: the
  coverage floor in the replay gate was refusing revisions that automated *less*
  than the agent proposed: the system was declining to let a person be more
  careful. The floor now applies to proposals and to widening revisions only.
  Zero false automatic actions is never waived.
- **The audit log is append-only** and hash-chained; `UPDATE` and `DELETE` are rejected by
  database triggers, and a test drops the triggers, tampers with a row, and asserts the
  chain notices.

The model provider sits behind an adapter: Bedrock, the Anthropic API, or a deterministic
implementation of the Strands `Model` interface that drives the unmodified agent loop
with no credentials and no network. That last one is why a judge can run the entire
product (real agent, real tool calls, real typed output) with `make setup && make seed
&& make run` and no AWS account. The same agent is deployed to Amazon Bedrock AgentCore
Runtime through a thin entrypoint (`agentcore_main.py`) and the AgentCore CLI's CDK
project, so the runtime is a transport detail rather than a second implementation.

## Beyond the demo domain

The fair question about any vertical demo: *is this just a returns app?*

It is not, and the repository can show it rather than argue it. Counting Python, the domain
pack and its adapters are 837 lines against 5,415 that know nothing about cameras: the
constrained policy language, the deterministic engine, the replay gate, the activation gate,
idempotent execution, read-back verification, the hash-chained audit log, the policy diff,
both database backends. (The web templates still speak returns, and that copy is not in the
count.) What knows about cameras lives in one
domain pack, which supplies six things: the fact record a policy may test and how it is
derived, the guardrails, the fixed action set with its caps, an executor and a verifier, a
labeled corpus to replay against, and the hard ceilings.

**So we shipped a second domain.** `ap.invoice_variance` governs an accounts-payable
exception: an invoice that does not match its purchase order. Same story, different room.
an AP clerk sees the same $42 freight variance twenty times a week, approves it in thirty
seconds, and never writes it down.

| | Returns | Accounts payable |
| --- | --- | --- |
| The recurring question | *a kit came back missing its lens cap, what do I do?* | *this invoice is $42 over the PO, do I pay it?* |
| Hard ceilings | $50 replacement, 1 component | $250 variance, 5% of the PO |
| Fixed actions | hold for parts, raise a work order, close | post a variance adjustment, release for payment, close |
| Guardrails | serial mismatch, new damage, safety-critical part, incomplete evidence | duplicate invoice, vendor on hold, no PO, receipt mismatch, tax mismatch, missing approver |
| Replay of the taught policy | 11 automated, 13 escalated, **0 wrong** | 12 automated, 12 escalated, **0 wrong** |

The second domain reuses every guarantee without changing a line of it, and adding it
*removed* 73 lines from the orchestrator, because returns-specific dispatch became a
domain's own business. A pack costs about 480 lines of Python plus its fixtures and tests.
`tests/test_domain_ap_invoices.py`, 17 tests touching no returns code, covers fact
derivation, every guardrail boundary, a policy language that refuses a field from another
domain, a replay across 24 labeled invoices, activation refused without a passing replay
and without a token, execution that pays once when run twice, verification that reads the
ledger back, and the audit chain intact.

Honest limits: the web screens and the agent's tools and prompts are still returns-shaped,
so the AP domain runs through the governance path and its tests rather than the agent loop
and the UI. And a domain has to reduce its judgment to allowlisted fields. Where a
decision genuinely turns on free-text nuance, there is nothing to replay and nothing to
bound, and this system will not automate it.

---

## Challenges

**Making "the model can't do that" true rather than asserted.** The first design had the
agent propose actions and validation reject bad ones. That's a check, and checks have
bugs. Moving the action set out of the proposal schema entirely turned it into a type
error instead.

**Deciding what a near-match should do.** Once a policy exists, a case that *nearly*
matches it is the most dangerous case in the system. It is exactly where a system that
wants to be helpful widens its own boundary. OneDecision escalates it and names the
condition that failed. Only an exception family with no approved policy at all produces a
fresh decision card.

**Being honest about AWS.** The build environment's AWS credentials turned out to be
invalid (`InvalidClientTokenId`). Rather than write deployment instructions from memory,
the AgentCore SDK was installed and introspected, the entrypoint was built and its routes
confirmed, and `docs/deployment-agentcore.md` states plainly which steps have not been run.
The hosted-model path was then run live with Claude Opus 5, first on the Anthropic API and
then on Amazon Bedrock through Opus 5's cross-Region inference profile. The smoke test
passes on both, with real tool calls and typed output. Each live run found something the
offline suite could not: two bugs in how Anthropic requests were built, and on Bedrock, a
concurrency bug where the model requested several tools at once and they collided on the
shared database connection. The agent escalated rather than act on the bad data, which is
the design working, and tools now run one at a time. All three fixes have regression tests.
The opt-in integration tests then passed on Bedrock, 3 of 3, after one more fix: a shared
test fixture had been forcing the offline provider, so those tests had always skipped.
Finally, the agent was deployed to AgentCore Runtime with the AgentCore CLI and invoked
live: it investigates a case on Bedrock and returns a decision card from AWS. It has since
been redeployed from current main, runtime version 2, and re-invoked, so the deployed
code is the code in the repository rather than a snapshot of an earlier week.

**A schema the model had to guess, and what it cost.** One Bedrock run of the demo used
169,000 tokens, and 115,000 of them were a single step: proposing the policy. The cause was
not the model. The agent proposes conditions and a spend cap (the action set is assembled
server-side), but the tool that dry-runs a candidate demanded the *full stored policy*,
actions and all, and its docstring never said so. So the model discovered a second,
undocumented schema by trial and error: in one take, 17 of 23 replay calls were schema
errors, one of them probing with an action literally typed `probe_invalid`. Making the
tool accept the shape the agent already returns, and saying so in the prompt along with two
validator rules it kept tripping over, took that step from 15 model cycles and 115K tokens
to 4 cycles, 2 replays and 19K, measured on the live golden path, not estimated. Bedrock
prompt caching is now on, which moved most remaining input to cache reads, and the
dashboard shows cached tokens separately so its own arithmetic still adds up.

**An agent that described the product wrongly.** A decision card on Bedrock told the
supervisor that approving would "also activate a standing policy". It does not: approval
records a decision and asks for a candidate, and only a person's separate activation, after
a passing replay, makes a policy live. The prompt had said actions happen "after a human
has approved it", which reads as approve-then-activate. That is a product claim appearing
on screen, so the fix was the prompt plus a check in the take verifier that fails any
recording whose card makes that claim.

## Accomplishments

- A working end-to-end loop where a human teaches an agent **once** and the boundary
  actually holds afterwards.
- **Zero** false automatic actions, **zero** prohibited actions, and **zero** duplicate
  actions across 24 evaluation cases, measured by a harness that counts from the
  database, not asserted.
- 199 hermetic tests on a clean clone, 401 runs across PostgreSQL and SQLite together in
  under forty seconds, including prompt injection inside case notes, audit tampering,
  model timeouts, tool outages, and duplicate events. CI runs the whole suite, the smoke
  test, the golden path, and the safety gate on every push, and fails the build if the
  PostgreSQL half silently skipped.
- **A second domain on the same machinery**: accounts-payable invoice variance, 17 tests,
  proven on both backends, with no change to the governance code.
- **Verified from a clean clone**: a fresh `git clone`, no AWS account, no credentials, no
  `.env`: setup, seed, tests, smoke, demo and eval, then the whole teach-once loop over
  HTTP, ending with the audit chain intact.
- The same Strands agent runs live on Claude Opus 5 through both the Anthropic API and
  Amazon Bedrock, deployed on AgentCore Runtime, and fully offline with no credentials.
- A replay gate that shows a supervisor what a proposed policy *would have done* to their
  own history before they trust it.

## What we learned

The hard part of a professional agent is not capability, it is **authority**. An agent
that can do the work is a weekend. An agent a manager will actually let act unattended
needs a boundary that is enforced somewhere the model cannot reach, and evidence about
that boundary that a non-engineer can read in thirty seconds.

The second lesson was cheaper to learn and easier to repeat: when an agent burns tokens,
look at the seams before the prompt. Every expensive loop in this build came from the model
reconciling two descriptions of the same thing: a tool that wanted one shape while the
schema returned another. Fixing the seam was worth six times what fixing the wording was.

## What's next

PostgreSQL behind the AgentCore deployment, so taught policies persist across sessions
rather than living in a per-session database. The screens and the agent's tools and prompts
for the second domain, which today runs through the governance path and its tests rather
than the UI. Policy expiry with periodic re-replay against newer history, so a boundary
taught in March has to re-earn its place in September. Event-driven triggers (a queue or
an event bus feeding the same gated path) now that a scheduled invocation has shown the
runtime will do the work with nobody watching. And the opt-in integration tests against the
Anthropic API.

---

## Built with

`python` · `strands-agents` · `amazon-bedrock` · `amazon-bedrock-agentcore` · `fastapi` ·
`pydantic` · `postgresql` · `sqlite` · `jinja2` · `pytest`

## Try it out

- Repository: https://github.com/mgraves-centrix/onedecision
- Run locally: `make setup && make seed && make run`, with no AWS account and no credentials
- Architecture: `docs/architecture.png`, and `docs/architecture.html` for the hoverable
  version, where each component lights up what it connects to and which way data moves
- **[OWNER]** demo video link

## AWS Builder ID

`@cloudyai`
