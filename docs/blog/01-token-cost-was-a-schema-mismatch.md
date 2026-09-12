# Agents for Humans: cutting Bedrock agent tokens by 83%

One run of our demo used 169,000 tokens. One step accounted for 115,000 of them: asking the
agent to propose a policy. That step took 129 seconds and 15 model cycles.

The reflex is to blame the model, or to swap in a smaller one. Both would have been wrong.
The tokens were going somewhere specific, and the audit log said where.

## What the numbers said

Every agent invocation writes an `agent.run` record: step, cycles, tool calls, input and
output tokens, duration. Reading them took a minute:

```
investigation    cycles=3   tools=4    15.4s   11,109 tokens
decision_card    cycles=1   tools=0    27.9s    6,131 tokens
policy_proposal  cycles=15  tools=24  129.2s  114,748 tokens
```

Twenty-four tool calls in one step, when the job needs roughly one. So we read the failures:

```
2x  "actions: Field required; max_cost_usd: Extra inputs are not permitted"
2x  "a policy that creates a work order must bound replacement_cost_usd with lt/lte"
1x  "actions.0: Input tag 'probe_invalid' found using 'type' does not match..."
```

That last one is the tell. The model was probing with an action type named `probe_invalid`,
which is what something does when it is working out a schema by watching what the validator
rejects.

## The actual cause

Our design is firm about one thing: the agent proposes *conditions and a spend cap*, never
actions. The action set is built server-side, so "the model invented an action" is not a
failure we have to catch. There is no field to write one into.

But before offering a proposal, the agent has to dry-run it through a
`replay_candidate_policy` tool, and that tool checked it against the **full stored policy**:
actions required, unknown fields rejected. Its docstring said only "the candidate policy as
a JSON object".

So we asked the model to work in one shape and gave it a tool that wanted another, without
describing either. Seventeen of the twenty-four replay calls in that take were schema
errors, and every retry resent a growing conversation. That is the 104,000 input tokens.

## The fix

Two changes, neither clever:

1. The replay tool now takes the same fields the agent already returns, through the same
   server-side conversion the real proposal uses. Actions still come only from the system;
   any the model sends are dropped and reported back.
2. The prompt states the two rules the model kept hitting by accident (a cost bound is
   required, nothing may exceed the ceiling) and asks for one replay of the candidate it
   means to offer, repeated only if that replay fails.

Measured on the live path afterwards:

| | Before | After |
|---|---|---|
| Model cycles | 15 | 4 |
| Replay calls (failed) | 24 (17) | 2 (0) |
| Tokens | 114,748 | 19,263 |
| Wall clock | 129 s | 42 s |

The two remaining replays are the intended pattern: the first candidate would have wrongly
actioned one historical case, so the model tightened it and the second came back clean.

## Then caching broke our own dashboard

With the loop fixed, we turned on Bedrock prompt caching. Fresh input fell to tens of tokens
per step. That broke a number on our own dashboard: the tile read "62.1K" over a caption of
"32 in · 9,316 out", because Bedrock counts cache reads in `totalTokens` but not in
`inputTokens`. The figures stopped adding up, and any reader would have decided the
dashboard was wrong. It now reads "32 in · 52.8K cached · 9,316 out".

## What was left when the seam was fixed

With the loop down to four cycles, what is left is not a loop at all. We timed the three
model calls on one case:

```
investigation    15.2s   1,201 output tokens   3 cycles
decision_card    27.9s   2,222 output tokens   1 cycle
policy_proposal  22.5s   1,828 output tokens   2 cycles
```

The decision card is one straight run of writing: no tool calls, nothing to wait on but the
model. Across all three steps Claude Opus 5 wrote about **79 output tokens per second**, and
we were asking for 5,600 of them.

The next move looks obvious, so we measured it instead of assuming. Same case, same prompts,
on Claude Sonnet 5:

| | Opus 5 | Sonnet 5 |
|---|---|---|
| Output tokens per second | 79.4 | 83.5 |
| Decision card | 27.9 s | **14.6 s** |
| Policy proposal | 22.5 s | **33.3 s** |
| Whole loop | ~65.6 s | 63.7 s |

Five percent apart on speed, two seconds apart across the whole loop. Every difference in
the middle rows is *how much each model chose to write*, not how fast it writes. Sonnet's
card was quicker because it wrote half as much card; its policy proposal was eleven seconds
slower because it took an extra cycle and wrote 60% more, then reached the same eight
conditions anyway.

So a smaller model is not a speed lever here. The only levers left are writing less or
accepting the wait. We took the wait: the card's proposed boundaries are 44% of its output
and the most useful thing on the screen.

## What generalizes

When an agent burns tokens, look at the seams before the prompt. Every expensive loop we
found came from the model trying to square two descriptions of the same thing. A tool
description that disagrees with your schema is not a docs problem. It is a bill, paid per
retry.

Log usage per invocation from day one. We answered "where did 169,000 tokens go?" in about
a minute because the product already recorded cycles, tool calls and tokens per step as
ordinary audit events. Without that we would have been guessing at the prompt.

*OneDecision is a Strands Agents project built for the Agents for Humans hackathon:
https://github.com/mgraves-centrix/onedecision*
