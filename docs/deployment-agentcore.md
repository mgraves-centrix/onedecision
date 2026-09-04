# Deploying to Amazon Bedrock AgentCore Runtime

**Status: not deployed.** See [provenance.md](provenance.md) for the blocker. Everything
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

1. **Get Bedrock model access.** Enable the model named by
   `ONEDECISION_BEDROCK_MODEL_ID` in the target region, then confirm:
   ```bash
   aws sts get-caller-identity
   aws bedrock list-foundation-models --region "$AWS_REGION"
   ```
2. **Switch the provider.** `ONEDECISION_MODEL_PROVIDER=bedrock`. Run the opt-in
   integration test *before* deploying anything:
   ```bash
   ONEDECISION_MODEL_PROVIDER=bedrock pytest -m integration
   ```
   It asserts real tool calls, a typed report, reconciliation against the source systems,
   and a schema-valid policy proposal. If a hosted model fails these, fix that first —
   deploying will not help.
3. **Container image.** AgentCore Runtime serves an ARM64 container listening on
   `:8080`, which is exactly what `python -m app.agentcore` provides. Build for
   `linux/arm64`.
4. **Persistence.** The demo uses local SQLite (`var/onedecision.db`), which does not
   survive a stateless runtime. Before any real deployment, move `app/db.py` behind a
   durable store. This is the one genuine piece of work between here and production,
   and it is deliberately not faked.
5. **Deploy.** Follow the current AgentCore Runtime deployment procedure in the AWS
   documentation (<https://docs.aws.amazon.com/bedrock-agentcore/>) — this document does
   not reproduce commands that have not been run here.
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
