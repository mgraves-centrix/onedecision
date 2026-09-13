# Devpost gallery

Fourteen images, 2880x1920 (3:2), each well under Devpost's 5 MB limit. Rebuild
with `python tools/gallery/build_gallery.py`.

Every shot is the running app, not a mockup. Images 1 to 5 come from a live
Bedrock run whose case is still waiting on a decision, so the card, the evidence
and the buttons are the real thing. Images 6 to 13 come from the finished take
that the demo video was recorded against.

Upload in this order. Devpost uses the first image as the project's thumbnail in
hackathon listings, so `00-cover.png` goes first: a dense screenshot is unreadable at that size. Captions are suggestions; Devpost takes one per image.

| # | File | Caption |
| --- | --- | --- |
| 0 | `00-cover.png` | Teach it once. It handles the next hundred decisions, and zero wrong automatic actions on 24 past cases before a person switched it on. |
| 1 | `01-inbox.png` | Six demo cases at the returns dock. Cases an approved policy covers resolve themselves and never appear as work. |
| 2 | `02-decision-card.png` | One decision card: what happened, what it costs, and what the agent recommends. Written to be read in thirty seconds. |
| 3 | `03-evidence.png` | Every line of evidence names the tool that produced it. Nothing on this card is unattributed. |
| 4 | `04-boundaries.png` | The agent proposes the boundaries the answer should live inside, and says plainly what it could not verify. |
| 5 | `05-the-decision.png` | The only two buttons. Approving records the decision and asks for a policy; it activates nothing. |
| 6 | `06-candidate-policy.png` | The proposed policy: conditions from an allowlist of nine fields, an action set fixed by the system, and exactly what changes against the active version. |
| 8 | `08-replay-gate.png` | The gate: 24 labeled historical cases replayed. Eleven automated, thirteen escalated, zero wrong. One wrong blocks activation. |
| 9 | `09-auto-resolved.png` | The next case, handled without a person. Work order raised, disposition set, both writes read back and verified. |
| 10 | `10-refusal.png` | Same kit, same cheap accessory, but the serial does not match. A hard guardrail runs before any policy is consulted. |
| 11 | `11-policies.png` | Policy versions: what each one allows, who activated it and when, and how it differs from the version before. |
| 12 | `12-dashboard.png` | What the agent handled, what it escalated, and what it cost, counted from the product's own records. |
| 13 | `13-audit-log.png` | Every event, tool call, approval and action in an append-only, hash-chained log the database refuses to edit. |
| 14 | `14-architecture.png` | One agent may propose. Deterministic code decides, acts and records. A person teaches the rule. |

The architecture diagram is also uploaded on its own as the required diagram, at
full resolution from `docs/architecture.png` (2880x2450 PNG, 0.6 MB).

There is no image 07. It was meant to show the policy diff, but its selector picked
up the evidence table, making it a near-duplicate of 03; the real diff is already in
frame in 06 and 11, so it was removed rather than re-shot.
