# Deploying to Amazon Bedrock AgentCore Runtime

**Status: not deployed.** AWS credentials and Bedrock model access are in place; see
[provenance.md](provenance.md). Everything
below was written against `bedrock-agentcore==1.22.0` and `strands-agents==1.54.0` as
actually installed and introspected — no CLI flags or API shapes are invented here. Steps
marked **unverified** have not been run in this environment.

## What is already in place

`app/agentcore.py` wraps the same `handle_event` path the local app uses:

```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp

agentcore_app = BedrockAgentCoreApp()

@agentcore_app.entrypoint
def handler(payload: dict) -> dict:
    return invoke(payload)
```

`BedrockAgentCoreApp` is a Starlette application exposing `/invocations`, `/ping`, and
`/ws`. `app.run(port=8080)` serves it. Verified by construction:

```bash
pip install -e ".[agentcore]"
python -c "from app.agentcore import build_app; a = build_app(); print(sorted({r.path for r in a.routes}))"
# ['/invocations', '/ping', '/ws']
```

Invocation payload:

```json
{"case_id": "CASE-2002", "event_key": "optional-idempotency-key"}
```

The response is the same `HandlingResult` the local path returns, so the runtime is a
transport detail rather than a second implementation of the product.

## Run it locally on the AgentCore contract (no AWS)

```bash
pip install -e ".[agentcore]"
python -m app.agentcore          # serves on :8080
curl -s localhost:8080/ping
curl -s localhost:8080/invocations -H 'content-type: application/json' \
     -d '{"case_id": "CASE-2001"}'
```

## Remaining steps to deploy (unverified)

1. **Get Bedrock model access. Done.** Claude Opus 5 is available to the account, and
   `make smoke` passes against Bedrock. Check access with:
   ```bash
   aws bedrock get-foundation-model-availability --model-id anthropic.claude-opus-5 --region "$AWS_REGION"
   ```
2. **Switch the provider. Done.** `ONEDECISION_MODEL_PROVIDER=bedrock`. The smoke test and
   the opt-in integration tests pass against Bedrock:
   ```bash
   ONEDECISION_MODEL_PROVIDER=bedrock pytest -m integration
   ```
   It asserts real tool calls, a typed report, reconciliation against the source systems,
   and a schema-valid policy proposal. If a hosted model fails these, fix that first —
   deploying will not help.
3. **Container image.** AgentCore Runtime serves an ARM64 container listening on
   `:8080`, which is exactly what `python -m app.agentcore` provides. Build for
   `linux/arm64`.
4. **Persistence. Done.** This was the one genuine gap; it is now closed. The
   application runs on PostgreSQL by setting `ONEDECISION_DATABASE_URL`, and the
   full test suite passes against both backends. Porting it also fixed three
   concurrency defects that a stateless, horizontally scaled runtime would have
   hit immediately. See [database.md](database.md), including the production
   hardening that is still outstanding — chiefly running as a non-owner role,
   secrets from Secrets Manager, TLS, and RDS Proxy in front of the pool.
5. **Deploy.** Follow the current AgentCore Runtime deployment procedure in the AWS
   documentation (<https://docs.aws.amazon.com/bedrock-agentcore/>) — this document does
   not reproduce commands that have not been run here.
   AWS now points to the AgentCore CLI (`npm install -g @aws/agentcore`, then
   `agentcore deploy`). Its project layout differs from this repository's, so the
   entrypoint needs adapting before it can be deployed that way.
6. **Observability.** Strands emits OpenTelemetry spans. Set `OTEL_EXPORTER_OTLP_ENDPOINT`
   and `ONEDECISION_OTEL_ENABLED=true` to export them; AgentCore's own tracing picks up
   the runtime side.

## Deliberately not used

**AgentCore Gateway, Memory, and Identity are not used.** The tool set is small, fixed,
and in-process; there is no cross-session memory to keep (each exception is evaluated from
current system state, by design); and the demo has a single role. Adding them would be
surface area, not capability.

## Costs

No billable infrastructure was created for this project. Deploying will incur Bedrock
inference and AgentCore Runtime charges.
