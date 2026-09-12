# Publishing the Builder posts

What goes in each field on AWS Builder Center, and why. The platform recommends a
title of 60 characters or fewer and a description of 160 or fewer, and says the
title is what appears in search results.

"Agents for Humans: " is required by the hackathon rules and costs 19 of the 60
characters, so everything after the colon has to carry the search value on its
own. That is the whole constraint.

## 1. Token cost

- **Title** (54): `Agents for Humans: cutting Bedrock agent tokens by 83%`
- **Description** (139): One run cost 169,000 tokens. A tool schema that disagreed
  with the prompt took 115,000 of them. Reading the audit log found it in a minute.
- **Tags**: `amazon-bedrock` `generative-ai` `cost-optimization` `observability` `python`
- **Cover**: `cover-01-token-cost.png`

The old title, "the 115,000-token step that was really a schema mismatch", named no
product and no term anyone searches. 83% is real: 114,748 tokens to 19,263.

## 2. EventBridge Scheduler to AgentCore

- **Title** (53): `Agents for Humans: EventBridge Scheduler to AgentCore`
- **Description** (140): EventBridge Scheduler can invoke Bedrock AgentCore directly,
  with no Lambda in between. The payload is raw JSON, whatever the CLI tells you.
- **Tags**: `amazon-bedrock` `amazon-eventbridge` `serverless` `aws-cli` `generative-ai`
- **Cover**: `cover-02-eventbridge.png`

"Bedrock" is dropped from the title only because both product names together run
61 characters. AgentCore is distinctive enough alone, and the description carries
"Bedrock AgentCore" in full.

## 3. Authority

- **Title** (54): `Agents for Humans: guardrails and human approval gates`
- **Description** (139): Every tool the agent has is read-only, and a policy it
  proposes replays against 24 labeled cases before a person is allowed to activate it.
- **Tags**: `amazon-bedrock` `generative-ai` `ai-agents` `security` `python`
- **Cover**: `cover-03-authority.png`

"The hard part is authority, not capability" is the better line and the worse
title: no product, no searchable term. The post's opening paragraph already makes
the same point, so nothing is lost by moving it out of the title.

## Verified on the platform

Post 1 published with `amazon-bedrock`, `generative-ai`, `cost-optimization`,
`observability` and `python`, all valid. `serverless`, `agents`, `ai-agents` and
`agentic-ai` also exist in the topic list at `builder.aws.com/learn/topics`.
Confirm `amazon-eventbridge`, `aws-cli` and `security` in the picker before
publishing; if one is missing, `serverless` and `ai-agents` are the fallbacks.
