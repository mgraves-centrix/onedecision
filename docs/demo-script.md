# Demo script — target 4:45 (hard limit 5:00)

Recorded against the live app on **Amazon Bedrock** (Claude Opus 5), so the banner reads
`bedrock · us.anthropic.claude-opus-5` and the Dashboard shows real token counts. The
offline `scripted` provider is the fallback: it reproduces exactly, costs nothing, and
the script works the same except for the tokens tile.

Timings are cumulative. Everything in brackets is on-screen action; everything else is
narration. Numbers marked *(read from screen)* come from the model's proposal and can
differ slightly between takes on Bedrock; the reference values are the offline run's.

---

## Before recording

1. `aws sso login --profile onedecision`
2. Start the app for the desktop browser and the phone (from the repo root):
   `AWS_PROFILE=onedecision ONEDECISION_MODEL_PROVIDER=bedrock .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000`
3. Browser at `http://127.0.0.1:8000`, window 1500×1000. Press **Reset demo**, so the
   Dashboard at the end counts only this take.
4. Phone on the same Wi-Fi or on Tailscale, with the Inbox open at
   `http://matts-macbook-air.onedecision.local:8000`.
5. A terminal tab with the AgentCore commands ready. **Pre-warm the runtime** by running
   the invoke once just before the take; a cold start took 46 seconds.
6. The approval token on a fresh clone is `replace-me-local-demo-token`; the activation
   screen prints it.

---

## 0:00 — 0:25 · The problem (Inbox view)

> This is OneDecision, a Strands Agents agent running on Claude Opus 5 through Amazon
> Bedrock.
>
> Dana runs returns for a camera rental company. Twenty times a week a kit comes back
> missing something small, and someone asks her what to do. She answers in thirty
> seconds, and she has never had an hour to write it down. Rule-based automation can't
> help: nobody wrote the rule. Everything you'll see is synthetic data.

[Inbox on screen. Point at the empty policy strip: *"No approved policy exists yet.
Every case needs a person."*]

---

## 0:25 — 1:10 · An unfamiliar exception arrives (Decision view)

> A kit is checked in at the dock. That's an **event**, not somebody typing a prompt at a
> chatbot.

[Click **Check in** on CASE-2001. The decision card loads.]

> The Strands agent just investigated it with four read-only tool calls: pull the case,
> reconcile what arrived against the bill of materials, price the missing part, and check
> for an approved policy.

[Scroll the evidence table. Point at the source-tool column.]

> Every line of evidence names the tool that produced it. One neoprene strap missing,
> fourteen dollars, serial matches, no damage, and **no approved policy exists**. So it
> doesn't act. It asks, once, and it proposes the **boundary** the answer should live
> inside.

[Scroll to Proposed boundaries.]

---

## 1:10 — 1:25 · Dana decides from her phone

[Cut to the phone. Open CASE-2001 and tap **Approve and teach**.]

> Dana isn't at her desk. She approves from her phone, between two other jobs. That's
> the whole interruption.

[Cut back to the desktop and refresh the case.]

---

## 1:25 — 2:10 · Teach, then replay

> Approving records her decision. It activates nothing.
>
> The agent now proposes a policy, and it can only propose in a constrained language:
> every condition comes from an allowlist of nine fields.

[Point at the conditions list *(read from screen)*.]

> And look at the actions: hold for parts, a replacement-parts work order under the spend
> cap, close the exception. **The agent didn't choose those.** The action set is fixed by
> the system; there is no field in the proposal where a model could write "issue a
> refund".
>
> Then deterministic code replays the candidate against twenty-four historical cases.

[Point at the replay stats *(read from screen; offline reference 11 / 13 / 0 / 100%)*.]

> It would have automated these, escalated these, and gotten **zero** wrong. If that
> number were anything but zero, the activate button would not be here.

---

## 2:10 — 2:30 · Explicit activation

[Type the approval token, click **Activate this policy version**.]

> A human activates it. That's the only path from candidate to active: it needs a token,
> and it's refused without a passing replay. The model can't do this; it's not a tool the
> agent has.

[Land on Policies & Audit. Point at `returns.missing_accessory@v1`, activated by Dana.]

---

## 2:30 — 3:00 · The next hundred (Inbox)

[Back to Inbox. Click **Check in** on CASE-2002.]

> Another kit, missing a body cap. Same investigation, but this time an approved policy
> matches.

[Open the resolved case. Scroll the timeline.]

> Work order raised, disposition set, both writes read back and verified, exception
> closed against policy version one. Dana never saw this case.

---

## 3:00 — 3:40 · The boundary holds

[Back to Inbox. Check in CASE-2003.]

> Now one that looks almost identical: same kit, one cheap accessory missing. **The
> serial doesn't match.** The wrong body came back.

[Open the escalated case. Point at the red escalation reasons.]

> It refuses. Not because a prompt told it to be careful: a hard guardrail runs before
> any policy is consulted, and a policy can only ever narrow what's allowed.

[Optionally check in CASE-2005 (new damage) and CASE-2006 (a tool outage). Both refuse.]

> Damage escalates. A failed tool escalates. The preferred answer is always "ask a
> person".

---

## 3:40 — 4:00 · The same agent on AgentCore Runtime (terminal)

[Terminal. Run `agentcore invoke "Investigate CASE-2001"`; the runtime is pre-warmed.]

> The same agent is deployed to Amazon Bedrock AgentCore Runtime. An invocation from AWS
> runs the same four tools on Bedrock and returns the same decision card: nothing
> executed until a person approves.

[Point at `"outcome": "decision_requested"` and the tool calls in the response.]

---

## 4:00 — 4:30 · The Dashboard

[Open **Dashboard**.]

> Everything this take did, counted from the product's own records: cases by outcome, the
> share handled automatically, the escalations, every agent run and tool call, and the
> tokens Bedrock reported.

[Point at the outcome bars, the tool-call bars, the tokens tile, and **Audit chain:
Intact**.]

---

## 4:30 — 4:45 · The receipts

> Every event, tool call, approval, and action is in an append-only, hash-chained log the
> database refuses to edit. Across twenty-four evaluation cases: one hundred percent
> correct escalation, **zero false automatic actions, zero prohibited actions, zero
> duplicates**.
>
> Teach the agent once; it safely handles the next hundred.

**[END — 4:45]**

---

## Notes for the recording

- **Reset between takes:** the **Reset demo** button, or `make seed`.
- **Rehearse once on Bedrock first.** The model's proposal can differ slightly between
  takes; read the conditions, spend cap, and replay numbers from the screen rather than
  from this script. Each take costs a few cents of Bedrock inference.
- **Fallback:** if a Bedrock take misbehaves, restart the app with
  `ONEDECISION_MODEL_PROVIDER=scripted` and record the same script; drop the tokens line
  at 4:00.
- **If a take runs long,** cut CASE-2005 / CASE-2006 at 3:30 first, then shorten the
  AgentCore beat to the invoke line alone. The serial-mismatch refusal carries the point.
- **Do not** show a terminal full of passing tests as filler; if there is spare time, show
  the audit timeline on CASE-2002 instead.
- **Say "synthetic" once, early.** The banner is on screen the whole time.
