# Demo script — target 4:15

Recorded against the local app with the offline provider, so it reproduces exactly.

**Before recording:** `make seed && make run`, browser at `http://127.0.0.1:8000`,
window at 1500×1000, terminal ready in a second tab.

Timings are cumulative. Everything in brackets is on-screen action; everything else is
narration.

---

## 0:00 — 0:25 · The problem (Inbox view)

> Dana runs returns for a camera rental company. Twenty times a week, a kit comes back
> missing something small, and someone walks over to ask her what to do. She answers in
> thirty seconds. She has never had an hour spare to write it down.
>
> Rule-based automation can't help — nobody wrote the rule. That's the gap OneDecision
> fills.

[Inbox on screen. Point at the empty policy strip: *"No approved policy exists yet.
Every case needs a person."*]

---

## 0:25 — 1:15 · An unfamiliar exception arrives (Decision view)

> A kit gets checked in at the dock. This is an **event**, not somebody typing a prompt
> at a chatbot.

[Click **Check in** on CASE-2001. The decision-card view loads.]

> A real Strands agent just investigated it. Four tool calls: pull the case, reconcile
> the bill of materials against what physically arrived, price the missing part, and
> check whether any approved policy already covers this.

[Scroll the evidence table. Point at the `source_tool` column.]

> Every line of evidence names the tool that produced it. One neoprene strap missing,
> fourteen dollars, serial matches, evidence complete, no damage — and **no approved
> policy exists**.
>
> So it does not act. It asks. Once.

[Scroll to Proposed boundaries.]

> This is the part that matters. It isn't just asking "yes or no" — it's proposing the
> **boundary** the answer should live inside, and saying why each limit is there.

---

## 1:15 — 2:10 · Approve and Teach (Replay)

[Click **Approve and teach**.]

> Approving records the decision. It activates nothing.
>
> The agent now proposes a policy — and it can only propose in a constrained language.
> Eight conditions, all from an allowlist of nine fields.

[Point at the conditions list.]

> And look at the actions: hold for parts, raise a replacement-parts work order capped at
> twenty-five dollars, close the exception. **The agent didn't choose those.** The action
> set is fixed by the system. There is no field anywhere in the proposal into which a
> model could write "issue a refund".
>
> Then deterministic code replays the candidate against twenty-four historical cases.

[Point at the replay stats: 11 / 13 / 0 / 100%.]

> Eleven it would have correctly automated. Thirteen it would have correctly escalated.
> **Zero it would have gotten wrong.** If that last number were anything but zero, the
> activate button would not be there.

---

## 2:10 — 2:35 · Explicit activation

[Type the approval token, click **Activate this policy version**.]

> A human activates it. That is the only path from candidate to active, it needs a token,
> and it's refused without a passing replay. The model has no way to do this — not a tool
> it's missing, a function it cannot reach.

[Land on Policies & Audit. Point at `returns.missing_accessory@v1`, activated by Dana.]

---

## 2:35 — 3:10 · The next hundred (Inbox)

[Back to Inbox. Click **Check in** on CASE-2002.]

> Another kit, missing a body cap. Same investigation, same tools — but this time an
> approved policy matches.

[Open the resolved case. Scroll the timeline.]

> Work order raised. Disposition set to PARTS_HOLD. Both writes read back out of the
> systems and verified. Exception closed against policy version one.
>
> Dana was never interrupted. She never saw this case.

---

## 3:10 — 3:50 · The boundary holds

[Back to Inbox. Check in CASE-2003.]

> Now a case that looks almost identical: same kit, one cheap accessory missing, under
> twenty-five dollars.
>
> **The serial doesn't match.** Wrong body came back.

[Open the escalated case. Point at the red escalation reasons.]

> It refuses. Not because a prompt told it to be careful — because a hard guardrail runs
> before any policy is even consulted, and a policy can only ever *narrow* what's allowed,
> never widen it.

[Optionally: check in CASE-2005 — new damage, and CASE-2006 — a tool outage. Both refuse.]

> Damage escalates. A failed tool escalates. Anything ambiguous escalates. The system's
> preferred answer is always "ask a person".

---

## 3:50 — 4:15 · The receipts

[Policies & Audit view. Point at the hash-chain badge.]

> Every event, tool call, guardrail result, approval, action, and verification is in an
> append-only log. It's hash-chained, and the database rejects `UPDATE` and `DELETE`
> outright.
>
> Twenty-four evaluation cases. One hundred percent correct escalation. **Zero false
> automatic actions, zero prohibited actions, zero duplicates.**
>
> Teach the agent once; it safely handles the next hundred.

**[END — 4:15]**

---

## Notes for the recording

- **Reset between takes:** the **Reset demo** button, or `make seed`.
- **If a take runs long,** cut the CASE-2005 / CASE-2006 boundary cases at 3:40; the
  serial-mismatch refusal alone carries the point.
- **Do not** show a terminal full of passing tests as filler; if there is spare time, show
  the audit timeline on CASE-2002 instead — it is the more convincing artifact.
- **Say "synthetic" once, early.** The banner is on screen the whole time; do not spend
  narration on it twice.
