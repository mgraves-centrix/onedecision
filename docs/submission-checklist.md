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
| 8 | Architecture diagram | **Done** | `docs/architecture.json` is the model; `tools/diagram/build_architecture.py` renders `docs/architecture.svg`, `.png`, and the hoverable `docs/architecture.html`. `docs/architecture.mmd` is the earlier Mermaid source, kept for reference. |
| 9 | AWS Builder ID | **Done** | `@cloudyai` |
| 10 | Public YouTube or Vimeo demo, ≤ 5 minutes | **Owner** | Recorded and cut: `../onedecision-video/onedecision-demo-draft-12.mp4`, 3:21, 1920x1080. Every desktop beat is the live app on Bedrock; the phone beat is a real iOS screen recording; the AgentCore beat replays a real invocation. `check_take.py` passes all 10 narration claims against the take's own database. Publishing needs the owner's account. |
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
| Builder.aws posts (0.2 each, max 0.6) | **3 of 3 published** | [1: token cost](https://builder.aws.com/content/3JFMPcu0rekYa1Y6LC5qt6vCctv/agents-for-humans-the-115000-token-step-that-was-really-a-schema-mismatch) (slug still carries its original title) · [2: EventBridge to AgentCore](https://builder.aws.com/content/3JFSvpuFac2q3oGJzdybB46V9CS/agents-for-humans-eventbridge-scheduler-to-agentcore) · [3: guardrails and approval gates](https://builder.aws.com/content/3JFVF2VqkKqTA9DZkzC9OzvbVQT/agents-for-humans-guardrails-and-human-approval-gates). Open: add posts 1 and 2 to the "Building OneDecision" series, and update their sign-offs per `docs/blog/publishing.md`. |
| AWS promotional credits | **Unavailable** | The resources page says all credits for this hackathon have been disbursed. |

## How judges will actually evaluate this

The rules say: *"Judges are not required to test the Project and may choose to
judge based solely on the text description, images, and video provided in the
Submission."*

Treat the video as the primary artifact, not a supplement. It is built to prove
the entire workflow on its own, including the refusal, which is the part that
distinguishes this from an agent that merely acts. `docs/demo-script.md` holds
the shot list; `tools/video/narration.json` is what is actually spoken.

## Judging categories (equally weighted; Technological Implementation is the first tie-breaker)

| Category | Where this project makes its case |
| --- | --- |
| Technological Implementation | Real Strands agent; constrained policy DSL; replay-gated activation; hash-chained audit; 199 hermetic tests, 401 runs against both PostgreSQL and SQLite; swappable model provider; deployed to AgentCore Runtime and fired unattended from EventBridge Scheduler. The domain is a pack: a second one, accounts-payable invoice variance, ships on the same machinery and changed none of it. |
| Design | Four coherent views, including a dashboard of history and usage; the decision card is the product surface; every claim on screen is traceable to a tool call; the policy diff makes a widened boundary impossible to approve by accident; a model call reports its own steps while it runs, so a forty-second wait is legible instead of a frozen page. |
| Potential Impact | Any recurring human judgment call with a bounded action space: returns, claims, refunds, exceptions, approvals. |
| Creativity & Originality | Not "an agent that writes SOPs". It converts one human decision into governed, replay-tested automation, and proves what it *would have done* before anyone trusts it. |
| Presentation | A 3:21 video that proves the whole workflow, including the refusal, on the live app rather than slides. |

## Blockers requiring the owner

Everything below needs an account this project does not have, and explicit
authorization. Nothing else is outstanding.

1. **Publish the demo video** to YouTube or Vimeo, and put the link in row 10.
   The cut is done; only the upload is blocked.
2. **Submit on Devpost**, from `docs/submission-draft.md`.
3. **Finish the Builder posts.** All three are published. Two things remain:
   add posts 1 and 2 to the "Building OneDecision" series (post 3 created it and
   is currently its only article), and replace their sign-offs with the
   cross-linked versions in `docs/blog/publishing.md`.

## Pre-submission verification

```bash
make setup && make seed && make test && make demo && make eval
```

All five must pass from a clean clone before submitting. Last verified against a
fresh clone on 2026-09-12: 199 passed, 7 skipped on SQLite alone, and 401 passed
on SQLite and PostgreSQL together.
