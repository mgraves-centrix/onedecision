# Agents for Humans: guardrails and human approval gates

An agent that can do the work is a weekend. An agent someone will let act unattended is a
different project, and almost none of that project is capability. It is authority: deciding
where the boundary sits, and enforcing it somewhere the model cannot reach.

Our test case: a returns supervisor gets asked the same question twenty times a week.
*A camera kit came back missing a $14 strap, what do I do?* She answers in thirty seconds
and never gets the hour it would take to write it down. Nobody wrote the rule, so rules
cannot help. Suggest an agent and the honest objection arrives: *how would I know it won't
do something stupid on the one case that's different?*

That objection is the requirement.

## Where we put the boundary

The agent may propose. It may never act. Not as a policy but as a shape:

- **Every tool the agent has is read-only.** `execute_approved_policy`, `verify_action` and
  activation are ordinary functions that were never registered as tools.
- **Policies are data.** A policy is conditions over an allowlist of nine fact fields with
  typed values and hard ceilings. No generated code, no SQL, no natural-language conditions,
  no `eval` anywhere in the engine.
- **The agent does not choose actions.** The proposal schema has no field for one, so "the
  model invented an action" is a missing field rather than a check that might have a bug.
- **Facts come from the systems, not the model.** The agent's report is checked against
  facts worked out separately; a disagreement escalates. A hallucination, or a prompt
  injection in an inspector's note, can only make the system more careful.
- **Guardrails outrank policies** and run before any policy is consulted.

## The part that makes it usable

None of that would matter to a supervisor. This is what does: before a taught policy can
act, deterministic code **replays** it against 24 labeled historical cases and reports what
it would have automated, escalated, and got wrong. One false automatic action blocks
activation. Then a person activates it, explicitly, with a token.

So "will it do something stupid?" stops being a matter of trust. It has an answer, in their
own data, before they commit to anything:

> Eleven cases it would have handled. Thirteen it would have sent to you. Zero it would have
> got wrong.

Nobody has to take the agent's word for that, or ours. The replay runs again, server-side,
at the moment of activation.

## What building it taught us

### Checks have bugs; missing fields don't

Our first design had the agent propose actions
and validation reject bad ones. Removing the field entirely turned a runtime check into a
type error.

### The dangerous case is the near-match

Once a policy exists, a case that *nearly* matches
is where a helpful system quietly widens its own boundary. Ours escalates and names the
condition that failed.

### Let people be more careful than the agent

Our replay gate enforced a coverage floor, so the agent couldn't propose a policy that
looked safe by doing nothing. That floor then refused a human revision which automated
*less* than proposed. The system was declining to let a person be careful. It now applies to
proposals and to widening revisions only. Zero false automatic actions is never waived.

### A gate nobody can sit through is not a gate

Approving a decision waits on a model call for forty seconds, and the page showed nothing
the whole time. On a phone that reads as a hung app, and a supervisor who thinks the tool is
broken will not trust what it says next. The fix was not speed. It was showing the run: each
phase and each tool call, with real timings, as the server reached them.

One detail cost us an afternoon and is worth knowing anywhere. A browser stops running
timers on a page it is leaving, so a form that submits the normal way can show a waiting
panel but can never update it. Ours sat on "Starting" for the full fifty seconds. Posting
the form with `fetch` and navigating after keeps the page alive, which is what makes live
steps possible at all.

### The agent will describe your product, so check what it says

On Bedrock, a decision card told the supervisor that approving would "also activate a
standing policy". It does not. The prompt said actions happen "after a human has approved
it", which reads as approve-then-activate. A claim about the product's own safety model,
generated at runtime, on screen. We fixed the prompt and added a check that fails any
recorded demo whose card makes that claim.

## Is it just a returns app?

Fair question, and one worth answering with code. In Python, the domain pack and its
adapters are 837 lines against 5,415 that know nothing about cameras: the policy language,
the engine, the replay and activation gates, retry-safe execution, read-back checks, the
audit log. Everything a domain owns lives in its pack. (The templates still speak returns,
and that copy is not counted.)

So we shipped a second pack: accounts-payable invoice variance. Different facts, guardrails,
ledger and actions. It reuses every guarantee without changing a line of them, and adding
the seam *removed* 73 lines from the orchestrator. Its 17 tests touch no returns code.

The limit is real and worth saying out loud: a domain has to boil its judgment down to
allowlisted fields. Where a decision really turns on what someone wrote in free text, there
is nothing to replay and nothing to bound, so this system will not automate it.

That is the trade. An agent that can act on anything cannot prove what it would have done.
We would rather ship the one that can prove it and automate less.

*OneDecision is a Strands Agents project built for the Agents for Humans hackathon:
https://github.com/mgraves-centrix/onedecision*
