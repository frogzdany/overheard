# Meeting script — Project Atlas quick sync (short demo cut)

Scripted 2-speaker meeting used as the audio source for the 2-minute demo
video (`docs/VIDEO-PLAN.md`, segment S2 "listening"). It is entirely
fictional and reuses the same cast as `fixtures/meeting-script.md`: **Ana**
(product lead) and **Daniel** (engineer), both at the fictional company
**Atlas Labs**. The only outside company mentioned is the fictional vendor
**Acme Corp**. No real people, companies, or products are referenced.

- Length: 174 words, ~1:11 spoken (target: 60–75s / ~150–180 words).
- Speakers: `Speaker 0` = Ana, `Speaker 1` = Daniel (see `speakers.json`).
- Four commitments, one per action kind actually exercised by the demo
  (no `draft_message` — the CopilotKit sidebar segment covers messaging),
  spread through the call in this order:

| # | ~Time | Kind | What happens |
|---|-------|------|--------------|
| a | 0:12 | `create_task` | Ana asks Daniel to send her the Q3 architecture diagram today; he agrees. |
| b | 0:28 | `schedule_followup` | They agree to a 30-minute follow-up next Tuesday at 10. |
| c | 0:44 | `create_doc` | Ana asks for a one-page rollout plan doc by Friday. |
| d | 0:58 | `lookup` | Daniel wonders what Acme Corp charges for their enterprise tier and asks to look it up. |

Everything else is realistic filler (a status check-in, hiring news) with no
actionable commitment attached, matching the pattern the suggestion brain is
tuned to ignore.

The exact machine-checkable version of this script is
`meeting-transcript.jsonl` (one JSON object per spoken line, with
timestamps). The four expected suggestions, in the engine's action contract
shape, are in `expected-actions.json`.

---

## Full transcript

**0:00.00 — Ana:** Hey Daniel, quick sync before the review. Got a minute?

**0:04.08 — Daniel:** Sure, go ahead.

**0:05.30 — Ana:** How's Project Atlas looking this week, any blockers?

**0:08.57 — Daniel:** Good progress, the ingestion pipeline's holding up fine.

> **[MOMENT (a) → create_task]**

**0:11.84 — Ana:** Nice. Before we dive in, can you send me the Q3 architecture diagram today? I need it for leadership this afternoon.

> **[MOMENT (a) confirmed]**

**0:20.41 — Daniel:** Yeah, I'll send you the diagram today, within the hour.

**0:24.49 — Ana:** Did the load numbers come back yet?

**0:27.35 — Daniel:** Not yet, still running overnight.

> **[MOMENT (b) → schedule_followup]**

**0:29.39 — Ana:** Let's plan a follow-up once those are in. Thirty minutes, next Tuesday at ten?

> **[MOMENT (b) confirmed]**

**0:35.10 — Daniel:** Tuesday at ten works, I'll block thirty minutes on my calendar.

**0:39.59 — Ana:** Great, I'll send the invite.

**0:41.63 — Daniel:** Also, hiring's looking up, we got a signed offer out.

> **[MOMENT (c) → create_doc]**

**0:45.71 — Ana:** Separately, for the executive review, I need a one-page rollout plan. Can you have a draft by Friday?

> **[MOMENT (c) confirmed]**

**0:53.06 — Daniel:** Friday works, I'll put together a one-pager covering scope, timeline, and key risks for the rollout.

> **[MOMENT (d) → lookup]**

**0:59.59 — Ana:** One more thing, does anyone know what Acme Corp charges for their enterprise tier?

> **[MOMENT (d) confirmed]**

**1:05.30 — Daniel:** Not off the top of my head. I'll look it up after the call.
