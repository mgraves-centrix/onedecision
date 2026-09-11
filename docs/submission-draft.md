# Devpost submission draft

> Draft copy for the Devpost form. Nothing here has been submitted. Fields marked
> **[OWNER]** need information or authorization only the submitter can supply.

---

## Project name

**OneDecision**

## Elevator pitch (200 characters)

> Teach the agent once; it safely handles the next hundred. OneDecision turns one
> approved human judgment call into a replay-tested, human-activated policy — and
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
written policy — let alone into automation. The knowledge stays in their head. The
interruptions keep coming. And the moment you suggest automating it, the honest objection
lands: *how would I know it isn't going to do something stupid on the one case that's
different?*

That objection is the real product requirement. Not "can an agent do this", but "can a
person hand over judgment and still be able to sleep".

## What it does

OneDecision watches one narrow class of exception — a returned high-value camera kit that
came back missing an accessory — and closes the learning loop exactly once.

1. An exception arrives **as an event**, not as a chat prompt.
2. A Strands agent investigates with tools: pulls the case, reconciles the bill of
   materials against what physically arrived, prices the missing part, and checks for an
   approved policy.
3. No policy covers it — so it produces **one compact decision card**: the evidence and
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

## How we built it

**Python 3.11 · Strands Agents SDK · FastAPI · Pydantic · PostgreSQL, with SQLite as the
zero-setup demo backend · server-rendered HTML.** One process, no build step, no client
framework.

There is exactly **one** Strands agent. It is invoked three times along the path —
investigate, produce the decision card, propose the policy — with the same tools and a
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
  which a model could write "issue a refund" — the action set is assembled from the
  allowlist server-side. That whole class of failure is a missing field, not a check.
- **Facts come from the systems, not the model.** The agent's report is reconciled
  against independently derived facts; any disagreement escalates. A hallucination — or a
  prompt injection buried in an inspector's note — can only make the system *more*
  conservative.
- **Hard guardrails outrank policies** and run before any policy is consulted. A policy
  can only ever narrow automation.
- **Replay gates activation.** One false automatic action against history blocks it.
- **A human can revise the boundary, and the diff says which way it moved.** The
  supervisor can tighten the agent's proposal or loosen it within the guardrails;
  the diff labels every change narrower or wider, and a revision is replayed from
  scratch before it can be activated. Building this surfaced a real flaw: the
  coverage floor in the replay gate was refusing revisions that automated *less*
  than the agent proposed — the system was declining to let a person be more
  careful. The floor now applies to proposals and to widening revisions only.
  Zero false automatic actions is never waived.
- **The audit log is append-only** and hash-chained; `UPDATE` and `DELETE` are rejected by
  database triggers, and a test drops the triggers, tampers with a row, and asserts the
  chain notices.

The model provider sits behind an adapter: Bedrock, the Anthropic API, or a deterministic
implementation of the Strands `Model` interface that drives the unmodified agent loop
with no credentials and no network. That last one is why a judge can run the entire
product — real agent, real tool calls, real typed output — with `make setup && make seed
&& make run` and no AWS account.

## Challenges

**Making "the model can't do that" true rather than asserted.** The first design had the
agent propose actions and validation reject bad ones. That's a check, and checks have
bugs. Moving the action set out of the proposal schema entirely turned it into a type
error instead.

**Deciding what a near-match should do.** Once a policy exists, a case that *nearly*
matches it is the most dangerous case in the system — it is exactly where a system that
wants to be helpful widens its own boundary. OneDecision escalates it and names the
condition that failed. Only an exception family with no approved policy at all produces a
fresh decision card.

**Being honest about AWS.** The build environment's AWS credentials turned out to be
invalid (`InvalidClientTokenId`). Rather than write deployment instructions from memory,
the AgentCore SDK was installed and introspected, the entrypoint was built and its routes
confirmed, and `docs/deployment-agentcore.md` states plainly which steps have not been run.
The hosted-model path was then run against the live Anthropic API with Claude Opus 5: the
smoke test passes with real tool calls and typed output. Running it live surfaced two bugs
in how requests were built that the offline suite could not see, and both are fixed with
regression tests. The Bedrock provider is implemented and configured for Opus 5's
cross-Region inference profile, but has not yet been run against a live Bedrock endpoint.

## Accomplishments

- A working end-to-end loop where a human teaches an agent **once** and the boundary
  actually holds afterwards.
- **Zero** false automatic actions, **zero** prohibited actions, and **zero** duplicate
  actions across 24 evaluation cases — measured by a harness that counts from the
  database, not asserted.
- 135 hermetic tests, run against both PostgreSQL and SQLite for 270 total runs in
  under thirty seconds, including prompt injection inside case notes,
  audit tampering, model timeouts, tool outages, and duplicate events. CI runs the
  whole suite, the smoke test, the golden path, and the safety gate on every push.
- A replay gate that shows a supervisor what a proposed policy *would have done* to their
  own history before they trust it.

## What we learned

The hard part of a professional agent is not capability, it is **authority**. An agent
that can do the work is a weekend. An agent a manager will actually let act unattended
needs a boundary that is enforced somewhere the model cannot reach, and evidence about
that boundary that a non-engineer can read in thirty seconds.

## What's next

A live Bedrock run and an AgentCore Runtime deployment, policy expiry and periodic
re-replay against newer history, and a second exception family, chosen to test whether
the policy language generalizes or was quietly fitted to the first one.

---

## Built with

`python` · `strands-agents` · `amazon-bedrock-agentcore` · `fastapi` · `pydantic` ·
`postgresql` · `sqlite` · `jinja2` · `pytest`

## Try it out

- Repository: https://github.com/mgraves-centrix/onedecision
- Run locally: `make setup && make seed && make run` — no AWS account, no credentials
- **[OWNER]** demo video link

## AWS Builder ID

`@cloudyai`
