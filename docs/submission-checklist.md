# Submission checklist

Deadline: **Monday, September 14, 2026, 5:00 PM Pacific / 8:00 PM Eastern.**
Target: submit by **noon Pacific on September 14**.

## Mandatory

| # | Requirement | Status | Notes |
| --- | --- | --- | --- |
| 1 | Project newly created during the submission period | **Done** | Started 2026-09-04 from an empty repository. See `docs/provenance.md`. |
| 2 | Strands Agents SDK central to the working product | **Done** | One `strands.Agent`, real `@tool` calls, typed structured output. `make smoke` prints it. |
| 3 | Agent performs real work end to end | **Done** | `make demo` runs event → investigation → decision → policy → replay → activation → automatic resolution → verification. |
| 4 | Public source repository | **Blocked — needs owner action** | Repository is private. Making it public requires explicit authorisation. |
| 5 | All source, assets, reproducible setup instructions | **Done** | `make setup && make seed && make run`. |
| 6 | README | **Done** | `README.md`. |
| 7 | MIT or Apache licence visible in the repository | **Done** | `LICENSE` (Apache-2.0). |
| 8 | Architecture diagram | **Done** | `docs/architecture.mmd` (source) + `docs/architecture.svg` / `.png` (rendered). |
| 9 | AWS Builder ID | **Blocked — needs owner action** | Must be supplied by the submitter. |
| 10 | Public YouTube or Vimeo demo, ≤ 5 minutes | **Not started** | Script ready at `docs/demo-script.md` (4:15). Record 2026-09-13. |
| 11 | Working product demonstration | **Done** | Local app; judges can run it with no cloud account. |
| 12 | Problem / audience / why it matters explained | **Done** | `README.md` and `docs/submission-draft.md`. |
| 13 | Free judge access through judging | **Done** | Runs locally with no credentials, no account, no spend. |
| 14 | Disclose incorporated non-standard pre-existing work | **Done** | None incorporated. `docs/provenance.md`. |
| 15 | Do not modify the project, repo, or video after the deadline | **Pending** | Freeze after submission. |

## Optional (strengthens Technical Implementation)

| Requirement | Status | Notes |
| --- | --- | --- |
| AgentCore Runtime deployment | **Blocked** | Entrypoint implemented and verified against the SDK; not deployed. AWS credentials in the build environment are invalid. `docs/deployment-agentcore.md`. |
| Live hosted-model demo | **Blocked** | Same blocker. Provider adapter and opt-in integration tests are ready. |
| Tracing / observability | **Partial** | Strands emits OTEL spans; wiring is documented, exporter not configured. |
| Builder.aws posts (0.2 each, max 0.6) | **Not started** | Stage Two only. Title must include "Agents for Humans". Publish before the deadline. |
| AWS promotional credits | **Deadline 2026-09-11 noon Pacific** | Requires owner action, while supplies last. |

## Judging categories (equally weighted; Technological Implementation is the first tie-breaker)

| Category | Where this project makes its case |
| --- | --- |
| Technological Implementation | Real Strands agent; constrained policy DSL; replay-gated activation; hash-chained audit; 94 hermetic tests; swappable model provider; AgentCore-ready entrypoint. |
| Design | Three coherent views; the decision card is the product surface; every claim on screen is traceable to a tool call. |
| Potential Impact | Any recurring human judgment call with a bounded action space — returns, claims, refunds, exceptions, approvals. |
| Creativity & Originality | Not "an agent that writes SOPs". It converts one human decision into governed, replay-tested automation, and proves what it *would have done* before anyone trusts it. |
| Presentation | 4:15 script that proves the whole workflow, including the refusal. |

## Blockers requiring the owner

1. **Make the repository public** — needs explicit authorisation.
2. **AWS Builder ID** — must be provided by the submitter.
3. **Record and publish the demo video** — needs an account and explicit authorisation.
4. **Bedrock / AgentCore access** — needs valid AWS credentials and model access.
5. **Devpost submission itself** — needs explicit authorisation.

## Pre-submission verification

```bash
make setup && make seed && make test && make demo && make eval
```

All five must pass from a clean clone before submitting.
