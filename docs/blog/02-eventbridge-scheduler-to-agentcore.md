# Agents for Humans: firing a Bedrock AgentCore invocation from EventBridge Scheduler

Our agent is event-driven: a returns dock emits a check-in, and the work starts. Nothing
polls. But we wanted to show the deployed agent doing real work with nobody watching, so we
pointed EventBridge Scheduler at Amazon Bedrock AgentCore Runtime.

Two things are worth writing down, because neither is obvious from the CLI help.

## You do not need a Lambda in between

EventBridge Scheduler's universal target can call the AgentCore data plane directly:

```
arn:aws:scheduler:::aws-sdk:bedrockagentcore:invokeAgentRuntime
```

The schedule's `Input` is the API request as JSON:

```json
{
  "AgentRuntimeArn": "arn:aws:bedrock-agentcore:us-west-2:<account>:runtime/<name>",
  "Payload": "{\"case_id\": \"CASE-2002\", \"event_key\": \"eventbridge-oneshot-...\"}",
  "RuntimeSessionId": "eventbridge-oneshot-session-...-onedecision-runtime",
  "ContentType": "application/json"
}
```

The execution role needs one action, scoped to the runtime:

```json
{"Effect": "Allow", "Action": "bedrock-agentcore:InvokeAgentRuntime",
 "Resource": ["<runtime-arn>", "<runtime-arn>/*"]}
```

Put `aws:SourceAccount` on the trust policy for `scheduler.amazonaws.com`, and set
`ActionAfterCompletion: DELETE` on a one-shot schedule so it removes itself.

## The payload is raw JSON, not base64

This cost us two firings. `InvokeAgentRuntime`'s `payload` is a blob, so base64 is the
instinct, and the AWS CLI enforces it, rejecting raw JSON with:

```
Invalid base64: "{"case_id":"CASE-2003",...}"
```

Follow that instinct in the schedule and the runtime logs:

```
"level": "WARNING", "message": "Invalid JSON in request (0.000s):
 Expecting value: line 1 column 1 (char 0)"
```

The schedule delivered; the handler received base64 text and could not parse it. Scheduler
passes the member through as written. Send **raw JSON** in the schedule's `Payload`, and use
`fileb://` with raw JSON for the CLI. Its own error message points the wrong way.

With that corrected, the runtime logged what we were after:

```
2026-09-12T02:28:51Z  "Invocation completed successfully (45.136s)"
  sessionId: "eventbridge-oneshot-session-...-onedecision-runtime"
```

Forty-five seconds is a real investigation on Claude Opus 5. The session ID is the one the
schedule supplied, which is what ties the run to the schedule rather than to a human at a
terminal.

## What it does not give you

The universal target is fire-and-forget. Scheduler does not read the response, so the
decision card that invocation produced went nowhere. If you need the outcome, and for
anything past a demo you do, put a small Lambda in between. Not because Scheduler cannot
reach the service, but because a scheduled sweep has to *list what is unhandled, build a
payload per item, and record what came back*. That is code, not target configuration.

A second limit, specific to how we deploy: each AgentCore session seeds its own SQLite
database, so a scheduled firing proves the gated path runs unattended. It does not carry
state from one firing to the next. We say that plainly rather than let it be assumed.

## Debugging notes that cost us time

`aws logs filter-log-events --start-time ...` returned zero events for a window that
definitely had them, including with no filter at all. The `agentcore logs --since 10m` CLI
returned them immediately. If your filter counts look impossible, check the tool before
concluding anything about the system. We reported "0 invocations" twice before realizing
the query was at fault.

Also: a `ResourceNotFoundException` from `get-schedule` after the fire time is the *success*
signal when `ActionAfterCompletion: DELETE` is set. It fired and cleaned up after itself.

## When to use this at all

For event-shaped work, don't schedule. Push. An event bus or a queue in front of the same
gated path gives you retries, a dead-letter queue and backpressure. Scheduler is the right tool
for time-based work: a nightly sweep, anything stuck in a waiting state past an SLA, a
retry of failed verifications. Using cron to simulate events is a demo trick, and reviewers
notice.

*OneDecision is a Strands Agents project built for the Agents for Humans hackathon:
https://github.com/mgraves-centrix/onedecision*
