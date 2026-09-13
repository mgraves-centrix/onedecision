# YouTube upload

Everything the YouTube Studio upload form asks for, in the order it asks. Files are
in this directory. The video is `../onedecision-video/onedecision-demo-draft-16.mp4`.

## Details

**Title** (74 of 100 characters)

```
OneDecision: Teach an AI Agent Once, It Handles the Next Hundred Decisions
```

Alternative, if you want the hackathon name first (46):

```
OneDecision | Agents for Humans Hackathon Demo
```

**Description** (2214 of 5,000 characters). Paste as is. The timestamps become
clickable chapters on their own: YouTube needs the first at 0:00, at least three, and
each at least 10 seconds long. The phone section is 7 seconds, so it shares a chapter
with teaching the policy.

```
Teach the agent once; it safely handles the next hundred decisions.

OneDecision is an AI agent for operations work: the same judgment call that lands on one person's desk twenty times a week. It is built with Strands Agents and runs on Claude Opus 5 through Amazon Bedrock.

When a case arrives that no rule covers, the agent investigates with read-only tools and asks a person once. From that one approved decision it proposes a narrow policy. Before that policy can do anything, deterministic code replays it against 24 past cases, and a person has to switch it on. After that it handles the matching cases by itself, and anything that looks similar but is not, it sends back to a person.

Built for the Agents for Humans hackathon, Professional Agents track.

CHAPTERS
0:00 The problem: judgment nobody has time to write down
0:31 An exception arrives and the agent investigates
1:06 Approving from a phone, and teaching a policy
1:46 A person activates it
1:58 The next case handles itself
2:16 The one that looks the same, and refuses
2:37 Deployed on Amazon Bedrock AgentCore
2:50 The dashboard
3:04 The audit trail, and why it matters

LINKS
Code (Apache-2.0): https://github.com/mgraves-centrix/onedecision
Write-ups on AWS Builder Center:
- Cutting Bedrock agent tokens by 83%: https://builder.aws.com/content/3JFMPcu0rekYa1Y6LC5qt6vCctv/agents-for-humans-the-115000-token-step-that-was-really-a-schema-mismatch
- EventBridge Scheduler to AgentCore: https://builder.aws.com/content/3JFSvpuFac2q3oGJzdybB46V9CS/agents-for-humans-eventbridge-scheduler-to-agentcore
- Guardrails and human approval gates: https://builder.aws.com/content/3JFVF2VqkKqTA9DZkzC9OzvbVQT/agents-for-humans-guardrails-and-human-approval-gates

HOW IT WAS MADE
Every screen in this video is the real app running live on Amazon Bedrock. The phone footage is a real iPhone screen recording. The company, customers, orders and serial numbers are synthetic demo data. The narration is a synthetic voice (Amazon Polly, voice Ruth).

BUILT WITH
Strands Agents · Claude Opus 5 · Amazon Bedrock · Amazon Bedrock AgentCore Runtime · Amazon EventBridge Scheduler · Python · FastAPI · PostgreSQL

#AgentsForHumans #StrandsAgents #AmazonBedrock
```

**Thumbnail:** upload `thumbnail.png` (1280x720, under YouTube's 2 MB limit). Custom
thumbnails need a phone-verified YouTube account; if the option is greyed out, verify at
youtube.com/verify first.

**Playlists:** none needed.

## Audience

**No, it's not made for kids.** Marking it for kids turns off comments, the info cards,
and the mini-player.

**Age restriction:** No, don't restrict.

## Show more

**Altered content: Yes.** The question YouTube asks is whether any sound or visuals were
significantly altered or synthetically generated in a way that could look real. The
narration is a synthetic voice, so the honest answer is yes. It costs nothing: YouTube
adds a small "altered or synthetic content" note in the expanded description, and the
footage itself is all real. Answering no when a synthetic voice narrates the whole video
is the one choice here that could come back to bite.

**Paid promotion:** No.

**Automatic chapters:** leave on; your description chapters take priority anyway.

**Featured places / concepts:** leave off.

**Tags** (214 of 500 characters). Comma separated:

```
OneDecision, Agents for Humans, Strands Agents, Amazon Bedrock, Bedrock AgentCore, Claude Opus 5, AI agents, human in the loop, AI governance, agentic AI, AWS, EventBridge Scheduler, Python, FastAPI, hackathon demo
```

**Language:** English. **Caption certification:** "This content has never aired on
television in the US."

**Recording date:** 12 September 2026. **Location:** leave blank.

**License:** Standard YouTube License. **Distribution:** Everywhere.

**Allow embedding:** On. Devpost embeds the video on your project page, and it will not
play there with embedding off.

**Publish to subscriptions feed:** your choice; it does not affect the submission.

**Category:** Science & Technology.

**Comments:** On. **Show how many viewers like this video:** On.

**Shorts remixing:** Allow video and audio remixing (the default). Every remix links back
to the original, so it is free discovery, and it does not stop anyone doing anything a
screen recording could not already do. The only reason to turn it off would be to keep
the synthetic narration from being reused out of context, and for a product demo that risk
is small.

## Video elements

**Subtitles:** Add, then "Upload file", "With timing", and choose `captions.en.srt`.
The timings come from the real pauses in the narration, not an estimate, so they will
not drift. Adding them also lets YouTube index every word of the voiceover for search.

**End screen and cards:** skip. The final 9 seconds is the closing card, and an end
screen would cover it.

## Checks

Copyright and ad-suitability checks should both come back clean: no music, the voice
is licensed through Amazon Polly, and all footage is your own.

## Visibility

**Public.** The hackathon rules require a public video; unlisted does not count.

Then copy the link into Devpost and into row 10 of `docs/submission-checklist.md`.
