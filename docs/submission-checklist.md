# Submission checklist

Deadline: **Monday, September 14, 2026, 5:00 PM Pacific / 8:00 PM Eastern.**
Target: submit by **noon Pacific on September 14**.

## Mandatory

| # | Requirement | Status | Notes |
| --- | --- | --- | --- |
| 1 | Project newly created during the submission period | **Done** | Started 2026-09-04 from an empty repository. See `docs/provenance.md`. |
| 2 | Strands Agents SDK central to the working product | **Done** | One `strands.Agent`, real `@tool` calls, typed structured output. `make smoke` prints it. |
| 3 | Agent performs real work end to end | **Done** | `make demo` runs event → investigation → decision → policy → replay → activation → automatic resolution → verification. |
| 4 | Public source repository | **Done** | Public at https://github.com/mgraves-centrix/onedecision. GitHub detects the Apache-2.0 license in the About sidebar. |
| 5 | All source, assets, reproducible setup instructions | **Done** | `make setup && make seed && make run`. |
| 6 | README | **Done** | `README.md`. |
| 7 | MIT or Apache license visible in the repository | **Done** | `LICENSE` (Apache-2.0). |
| 8 | Architecture diagram | **Done** | `docs/architecture.mmd` (source) + `docs/architecture.svg` / `.png` (rendered). |
| 9 | AWS Builder ID | **Done** | `@cloudyai` |
| 10 | Public YouTube or Vimeo demo, ≤ 5 minutes | **Not started** | Script ready at `docs/demo-script.md` (4:15). Record 2026-09-13. |
| 11 | Working product demonstration | **Done** | Local app; judges can run it with no cloud account. |
| 12 | Problem / audience / why it matters explained | **Done** | `README.md` and `docs/submission-draft.md`. |
| 13 | Free judge access through judging | **Done** | Runs locally with no credentials, no account, no spend. |
| 14 | Disclose incorporated non-standard pre-existing work | **Done** | None incorporated. `docs/provenance.md`. |
| 15 | Do not modify the project, repo, or video after the deadline | **Pending** | Freeze after submission. |

## Optional (strengthens Technical Implementation)

| Requirement | Status | Notes |
| --- | --- | --- |
| Live demo link | **Not started** | Explicitly optional: *"(Optional) Include a live demo link"*, which strengthens Technical Implementation. The AgentCore Runtime is deployed, but invoking it requires AWS credentials, so it is not a public link; a public link would need the web app hosted separately. The local build already satisfies the mandatory access rule. |
| AgentCore Runtime deployment | **Done** | Deployed to `us-west-2` with the AgentCore CLI (`agentcore deploy`) and invoked live; the runtime is `READY`. Each session seeds its own SQLite database, so state does not persist across sessions. `docs/deployment-agentcore.md`. |
| Live hosted-model demo | **Done** | `make smoke` passes live on both the Anthropic API (`claude-opus-5`) and Amazon Bedrock (`us.anthropic.claude-opus-5`), and the opt-in integration tests pass on Bedrock (3 of 3). |
| Tracing / observability | **Partial** | Strands emits OTEL spans; wiring is documented, exporter not configured. |
| Builder.aws posts (0.2 each, max 0.6) | **Not started** | Stage Two only. Title must include "Agents for Humans". Publish before the deadline. |
| AWS promotional credits | **Unavailable** | The resources page says all credits for this hackathon have been disbursed. |

## How judges will actually evaluate this

The rules say: *"Judges are not required to test the Project and may choose to
judge based solely on the text description, images, and video provided in the
Submission."*

Treat the video as the primary artifact, not a supplement. `docs/demo-script.md`
is built to prove the entire workflow on its own — including the refusal, which
is the part that distinguishes this from an agent that merely acts.

## Judging categories (equally weighted; Technological Implementation is the first tie-breaker)

| Category | Where this project makes its case |
| --- | --- |
| Technological Implementation | Real Strands agent; constrained policy DSL; replay-gated activation; hash-chained audit; 141 hermetic tests run against both PostgreSQL and SQLite (282 runs); swappable model provider; deployed to AgentCore Runtime. |
| Design | Three coherent views; the decision card is the product surface; every claim on screen is traceable to a tool call; the policy diff makes a widened boundary impossible to approve by accident. |
| Potential Impact | Any recurring human judgment call with a bounded action space — returns, claims, refunds, exceptions, approvals. |
| Creativity & Originality | Not "an agent that writes SOPs". It converts one human decision into governed, replay-tested automation, and proves what it *would have done* before anyone trusts it. |
| Presentation | 4:15 script that proves the whole workflow, including the refusal. |

## Blockers requiring the owner

1. **Record and publish the demo video** — needs an account and explicit authorization.
2. **Devpost submission itself** — needs explicit authorization.

## Pre-submission verification

```bash
make setup && make seed && make test && make demo && make eval
```

All five must pass from a clean clone before submitting.
