# Deploying to Amazon Bedrock AgentCore Runtime

**Status: deployed.** The agent runs on AgentCore Runtime in `us-west-2`. It was deployed
with the AgentCore CLI (`@aws/agentcore` 0.28.1) on 2026-09-11 and invoked live. Every
command below was run in this environment unless it is marked **not yet run**.

## What is deployed

- **`agentcore_main.py`** is the file AgentCore runs. It sits at the root of the
  deployment package so the `app` package imports beside it, and it calls `build_app()`
  from `app/agentcore.py`.
- **`app/agentcore.py`** wraps the same `handle_event` path the local app uses, so the
  runtime is a transport detail rather than a second implementation of the product:

  ```python
  from bedrock_agentcore.runtime import BedrockAgentCoreApp

  agentcore_app = BedrockAgentCoreApp()

  @agentcore_app.entrypoint
  def handler(payload: dict) -> dict:
      return invoke(payload)
  ```

- **`agentcore/agentcore.json`** is the AgentCore CLI project. It defines one runtime:

  ```json
  {
    "name": "onedecision",
    "build": "CodeZip",
    "entrypoint": "agentcore_main.py",
    "codeLocation": ".",
    "runtimeVersion": "PYTHON_3_13",
    "networkMode": "PUBLIC",
    "protocol": "HTTP",
    "envVars": [
      {"name": "ONEDECISION_MODEL_PROVIDER", "value": "bedrock"},
      {"name": "ONEDECISION_BEDROCK_MODEL_ID", "value": "us.anthropic.claude-opus-5"},
      {"name": "ONEDECISION_DB_PATH", "value": "/tmp/onedecision.db"}
    ]
  }
  ```

- **`agentcore/cdk/`** is the CDK app the CLI generated. `agentcore deploy` synthesizes and
  deploys it as the CloudFormation stack `AgentCore-OneDecision-default`.

Invocation payload, either form:

```json
{"case_id": "CASE-2002", "event_key": "optional-idempotency-key"}
{"prompt": "Investigate CASE-2002"}
```

The second form is what the SDK examples in the AgentCore documentation send; a case ID
named anywhere in the prompt is accepted.

## What this deployment shows, and what it does not

**Shows:** the same Strands agent, on Claude Opus 5 through Bedrock, running inside
AgentCore Runtime. `agentcore invoke "Investigate CASE-2001"` returned the case with four
real tool calls and a decision card recommending the $14.00 strap charge, with nothing
executed until a person approves. The runtime logs show no errors.

**Does not show:**

- **State across sessions.** Each runtime session seeds its own SQLite database under
  `/tmp`, so a policy taught in one session is not there in the next. The full
  teach-once loop runs in the local app. Persistent state would mean pointing
  `ONEDECISION_DATABASE_URL` at PostgreSQL (for example RDS, with VPC networking); the
  application supports it (see [database.md](database.md)), but it is not provisioned.
- **A public link.** Invoking the runtime requires AWS credentials with
  `bedrock-agentcore:InvokeAgentRuntime`. The web interface is not deployed.

## Deploy it yourself

Prerequisites: AWS credentials (an IAM Identity Center profile works), Node.js 20 or
later, `uv`, and Bedrock access to Claude Opus 5 (Anthropic's first-time-use form).
Run everything from the repository root. If you use a named profile, export
`AWS_PROFILE` first.

```bash
npm install -g @aws/agentcore
npm --prefix agentcore/cdk install
```

Create `agentcore/aws-targets.json`. It is gitignored so the account ID stays out of the
public repository:

```json
[{"name": "default", "account": "<account-id>", "region": "us-west-2"}]
```

```bash
agentcore validate
agentcore package                # builds the CodeZip locally; nothing is sent to AWS
agentcore deploy --dry-run
agentcore deploy --yes           # the first run bootstraps CDK in the account
agentcore invoke "Investigate CASE-2001"
agentcore status
agentcore logs --since 30m
```

What the packager does, from reading the CLI's packaging code and the built zip:

- It installs only `[project.dependencies]` from `pyproject.toml`, not extras, which is
  why `bedrock-agentcore` is a main dependency.
- It installs Linux ARM (`aarch64-manylinux`) wheels only. Every current dependency has
  one.
- It leaves out `.env`, `.env.local`, and `.env.*` at any depth, plus `.git`, `.venv`,
  `__pycache__`, and the `agentcore/` config directory. Everything else in the repository
  ships. The packaged zip is about 29 MB.

## Run it locally on the AgentCore contract (no AWS)

```bash
pip install -e .
ONEDECISION_MODEL_PROVIDER=scripted uvicorn agentcore_main:agentcore_app --port 8091
curl -s localhost:8091/ping
curl -s localhost:8091/invocations -H 'content-type: application/json' \
     -d '{"prompt": "Investigate CASE-2001"}'
```

`python agentcore_main.py` serves the same app on port 8080.

## Tear it down (not yet run)

```bash
agentcore remove all
agentcore deploy
```

`remove all` resets the project configuration, and the follow-up `deploy` removes the
resources from the account. The CDK bootstrap stack (`CDKToolkit`) stays; delete it from
the CloudFormation console after emptying its S3 bucket.

## Observability

The deployment enables CloudWatch logging and transaction search for the runtime;
`agentcore logs` and `agentcore traces list` read them. Strands also emits OpenTelemetry
spans. Set `OTEL_EXPORTER_OTLP_ENDPOINT` and `ONEDECISION_OTEL_ENABLED=true` to export
them elsewhere.

## Deliberately not used

**AgentCore Gateway, Memory, and Identity are not used.** The tool set is small, fixed,
and in-process; there is no cross-session memory to keep (each exception is evaluated from
current system state, by design); and the demo has a single role. Adding them would be
surface area, not capability.

## Costs

Bedrock inference for each invocation, AgentCore Runtime consumption while a session is
active, and small amounts of S3 storage (the CDK staging bucket and the code package) and
CloudWatch logs.
