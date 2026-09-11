# Provenance and disclosures

## Origin

OneDecision was created from scratch during the Agents for Humans submission period,
starting 2026-09-04. The repository began empty apart from an `Apache-2.0` LICENSE and a
one-line `README.md`; every other file in it was written for this hackathon.

## Pre-existing work incorporated

None. No pre-existing non-standard codebase, template, private library, or prior project
was incorporated.

Standard, publicly available third-party dependencies are used and pinned in
`pyproject.toml`:

| Package | Version | Role |
| --- | --- | --- |
| `strands-agents` | 1.54.0 | the agent framework — central to the product |
| `fastapi` / `starlette` | 0.141.1 | HTTP + server-rendered views |
| `pydantic` | 2.13.5 | typed structured output and the policy schema |
| `jinja2` | 3.1.6 | templates |
| `uvicorn` | 0.52.4 | ASGI server |
| `boto3` | 1.43.88 | pulled in by the Bedrock provider |
| `bedrock-agentcore` | 1.22.0 | **optional extra**, AgentCore Runtime entrypoint only |
| `pytest`, `pytest-asyncio`, `httpx` | dev | tests |

AI coding assistance was used during development, which the hackathon rules permit. All
architectural decisions, the safety model, the policy language, the evaluation design,
and the synthetic dataset were specified and reviewed by the author.

## Data

**All data in this repository is synthetic and fabricated for the demo.**

- The company (Northgate Optics), facility, personas, SKUs, serial numbers, order
  identifiers, customer references, inspection notes, and parts prices are invented.
- No real customer records, PII, private SOPs, credentials, confidential business data,
  or proprietary information appears anywhere in the repository or in the demo.
- Every "business system" the agent touches is a labeled synthetic adapter in
  `app/adapters/` backed by local SQLite. None is a production integration, and the UI
  states this on every page.

## Verified environment claims

Claims in this repository were checked, not assumed:

| Claim | How it was verified |
| --- | --- |
| Strands `Agent` runs with real tool calls and typed structured output | `make smoke` — prints the tool calls and the parsed `InvestigationReport` |
| `ScriptedModel` is a valid Strands `Model` implementation | it implements the four abstract methods of `strands.models.model.Model` and drives the unmodified Strands event loop |
| AgentCore entrypoint matches the real SDK | `bedrock-agentcore==1.22.0` installed in a scratch environment; `BedrockAgentCoreApp`, `@app.entrypoint`, and `app.run(port=…)` confirmed by introspection, and `build_app()` was constructed successfully, exposing `/invocations` and `/ping` |
| The evaluation numbers | produced by `python -m app.evaluation`, counted from the database after a real run |
| The Anthropic API provider works end to end | `make smoke` run against the live Anthropic API with `claude-opus-5` on 2026-09-10: four real tool calls and a parsed `InvestigationReport` |
| The Bedrock provider works end to end | `make smoke` run against Amazon Bedrock with `us.anthropic.claude-opus-5` in `us-west-2` on 2026-09-10: four real tool calls and a parsed `InvestigationReport`, after the concurrency fix described below |
| The opt-in integration tests pass against a hosted model | `pytest -m integration` against Bedrock (`us.anthropic.claude-opus-5`) on 2026-09-10: 3 passed. They cover real tool calls, a report that reconciles with the source systems, and a schema-valid policy proposal |

## AWS access

For most of the build, the environment's AWS environment variables were **not valid AWS
credentials**:

```
$ sts:GetCallerIdentity
ClientError: An error occurred (InvalidClientTokenId) when calling the
GetCallerIdentity operation: The security token included in the request is invalid.
```

On 2026-09-10 the project was connected to an AWS account through IAM Identity Center.
Current state:

- The **Bedrock** model provider (`app/agent/providers/__init__.py`) has been exercised
  against a live Bedrock endpoint: `make smoke` passes with `us.anthropic.claude-opus-5`
  in `us-west-2`. The first live run found a real defect: the model requested several
  tools in one turn, Strands ran them concurrently, and they collided on the shared
  database connection. Tools now run one at a time (`app/agent/build.py`,
  `tests/test_agent_build.py`). The opt-in integration tests pass there too (3 of 3),
  after a fix to the tests themselves: a shared fixture forced the offline provider,
  so they had always skipped.
- The **AgentCore Runtime** entrypoint (`app/agentcore.py`) builds against the real SDK
  and serves the correct contract locally, but has **not** been deployed to AgentCore.
- The only billable AWS usage is Bedrock inference for smoke tests. No compute, storage,
  or database resources were created, and no deployment was attempted.

The local golden path is complete, tested, and reproducible without any cloud account.
See [deployment-agentcore.md](deployment-agentcore.md) for what remains, written against
the SDK that is actually installed rather than from memory.

## What is claimed, and what is not

**Claimed:** a real Strands agent doing real work end to end; a constrained policy
language; a working activation gate; replay-gated learning; measured evaluation results;
an append-only audit log with tamper detection.

**Not claimed:** a running AgentCore Runtime; production integrations; a systematic
evaluation of a hosted model on this task. Live models on both the Anthropic API and
Bedrock have passed the smoke test, and the opt-in integration tests pass on Bedrock,
but three integration tests are not a systematic evaluation.
