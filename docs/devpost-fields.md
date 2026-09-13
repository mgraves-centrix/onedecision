# Devpost submission fields

Everything the form asks for, with the answer and where it comes from. The long
copy lives in `docs/submission-draft.md`.

## Testing instructions

Paste this into "testing instructions for application". It needs no AWS account,
no credentials and no network, which is what makes it usable by a judge.

> **Runs entirely on your machine. No AWS account, no API key, no network call.**
>
> ```
> git clone https://github.com/mgraves-centrix/onedecision && cd onedecision
> make setup     # virtualenv and pinned dependencies
> make seed      # build the demo database from synthetic fixtures
> make run       # http://127.0.0.1:8000
> ```
>
> Then walk the loop in the app, which takes about two minutes:
>
> 1. **Check in CASE-2001.** A kit came back missing a $14 strap. No policy
>    covers it, so the agent investigates with four read-only tool calls and puts
>    one decision card in front of you. Every line of evidence names the tool that
>    produced it.
> 2. **Approve and teach.** This records your decision. It activates nothing. The
>    agent then proposes a policy, and deterministic code replays that policy
>    against 24 labeled historical cases before offering it to you: eleven it
>    would have automated, thirteen it would have escalated, zero it would have
>    got wrong. One wrong action blocks activation.
> 3. **Activate the policy.** It asks for a token, because a person authorizing
>    automation is the point. On a fresh clone the token is
>    `replace-me-local-demo-token`, shown on screen.
> 4. **Check in CASE-2002.** Same shape of problem, a $6.50 body cap. The policy
>    matches, the work order is raised, both writes are read back and verified,
>    and the case closes without you.
> 5. **Check in CASE-2003.** Looks identical, but the serial does not match. It
>    refuses, names the guardrail that fired, and sends it to a person.
>
> The **Dashboard** counts all of it from the product's own records. **Policies &
> Audit** shows the hash-chained log.
>
> By default this runs a deterministic offline model, so the walkthrough is
> identical every time and costs nothing. To run it against the real model:
> `ONEDECISION_MODEL_PROVIDER=bedrock AWS_PROFILE=your-profile make run`, or
> `anthropic` with `ANTHROPIC_API_KEY`. `make smoke` prints the agent's real tool
> calls and typed output either way.
>
> Other checks: `make test` (199 tests, a few seconds), `make demo` (the golden
> path in the terminal), `make eval` (the evaluation harness).

## Architecture diagram (required)

`docs/architecture.png`, 2880x2450 PNG, 0.6 MB. Well inside the 35 MB limit.
Rendered from `docs/architecture.json` by `tools/diagram/build_architecture.py`.

## Gallery

Fourteen 3:2 images in `docs/gallery/`, with captions in `docs/gallery/README.md`.

## Bonus blog post

One URL field, three posts. Submit post 3:

    https://builder.aws.com/content/3JFVF2VqkKqTA9DZkzC9OzvbVQT/agents-for-humans-guardrails-and-human-approval-gates

It is the post about what makes the project different rather than a debugging
story, and its page carries the "Building OneDecision" series widget listing all
three, so one link surfaces the set.

## Live demo link

None. Deliberately, and worth stating plainly if the form allows a note: the app
is a FastAPI server, so a public link means hosting it somewhere, and the
deployed AgentCore Runtime needs AWS credentials to invoke. The mandatory free
judge access is satisfied by the local build above, which needs no account.
