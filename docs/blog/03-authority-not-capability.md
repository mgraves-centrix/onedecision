# Agents for Humans: the hard part is authority, not capability

An agent that can do the work is a weekend. An agent someone will let act unattended is a
different project, and most of that project is deciding where the boundary is enforced.

Our test case: a returns supervisor gets asked the same kind of question twenty times a
week — *a camera kit came back missing a $14 strap, what do I do?* — answers in thirty
seconds, and never gets the hour it would take to write it down. Rule-based automation
cannot help, because nobody wrote the rule. The moment you suggest an agent, the honest
objection arrives: *how would I know it won't do something stupid on the one case that's
different?*

That objection is the requirement.

## Where we put the boundary

The agent may propose. It may never act. Not as a policy but as a shape:

- **Every tool the agent has is read-only.** `execute_approved_policy`, `verify_action` and
  activation are ordinary functions that were never registered as tools.
- **Policies are data.** A policy is conditions over an allowlist of nine fact fields with
  typed values and hard ceilings. No generated code, no SQL, no natural-language conditions,
  no `eval` anywhere in the engine.
- **The agent does not choose actions.** The proposal schema has no field for one. The
  action set is assembled server-side. "The model invented an action" is a missing field,
  not a check that might have a bug.
- **Facts come from the systems, not the model.** The agent's report is reconciled against
  independently derived facts; a disagreement escalates. A hallucination — or a prompt
  injection in an inspector's note — can only make the system more conservative.
- **Guardrails outrank policies** and run before any policy is consulted.

## The part that makes it usable

None of that would matter to a supervisor. This is what does: before a taught policy can
act, deterministic code **replays** it against 24 labeled historical cases and reports what
it would have automated, escalated, and got wrong. One false automatic action blocks
activation. Then a person activates it explicitly, with a token.

So the question "will it do something stupid?" has an answer in their own data, before they
commit: *here are the eleven cases it would have handled, the thirteen it would have sent to
you, and the zero it would have got wrong.*

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

Our replay gate enforced a coverage floor so
the agent couldn't propose a policy that looked safe by doing nothing. That floor then
refused a human revision that automated *less* than proposed: the system declining to let a
person be conservative. The floor now applies to proposals and to widening revisions only.
Zero false automatic actions is never waived.

### A gate nobody can sit through is not a gate

Approving a decision blocks on a model
call for forty seconds. The page showed nothing for that whole time, which on a phone reads
as a hung app, and a supervisor who thinks the tool is broken does not trust what it tells
them afterwards. The fix was not making it faster. It was reporting what the run was
actually doing: each phase and each tool call, with real timings, as the server reached
them. The work is one synchronous transaction, so its audit rows are not readable by another
request until it commits; the panel is fed by a small in-memory channel beside it that
nothing which decides or records ever reads.

One detail cost us an afternoon and generalizes past this project: a browser suspends timers
on a document it is navigating away from. A page that submits a form normally can show a
waiting panel but can never update it. Ours sat on "Starting" for the full fifty seconds.
Posting the form with `fetch` and navigating afterwards keeps the document alive, which is
what makes the live steps possible at all.

### The agent will describe your product, so check what it says

On Bedrock, a decision card
told the supervisor that approving would "also activate a standing policy". It does not.
The prompt had said actions happen "after a human has approved it", which reads as
approve-then-activate. A claim about the product's safety model, generated at runtime, on
screen. We fixed the prompt and added a check that fails any recorded demo whose card makes
that claim.

## Is it just a returns app?

Fair question, and one worth answering with code. Counting Python, the domain pack and its
adapters are 837 lines against 5,415 of domain-neutral machinery: the policy language, the
engine, the replay and activation gates, idempotent execution, read-back verification, the
audit log. What knows about cameras is one pack: facts and how they're derived, guardrails,
a fixed action set, an executor and verifier, a labeled corpus. (The web templates still
speak returns; that copy is not in the count and would have to follow a second domain into
the UI.)

So we shipped a second pack: accounts-payable invoice variance. Different facts, different
guardrails, a different ledger, different actions. It reuses every guarantee without
changing a line of them, and adding the seam *removed* 73 lines from the orchestrator. Its
17 tests touch no returns code.

The limit is real and worth stating: a domain has to reduce its judgment to allowlisted
fields. Where a decision genuinely turns on free-text nuance, there is nothing to replay and
nothing to bound, and this system will not automate it. That is a constraint by
construction, not an oversight.

*OneDecision is a Strands Agents project built for the Agents for Humans hackathon:
https://github.com/mgraves-centrix/onedecision*
