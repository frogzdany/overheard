# Meeting script — Project Atlas sync (Ana & Daniel)

Scripted 2-speaker meeting used as a fixture for tuning Overheard's suggestion
brain. It is entirely fictional: **Ana** (product lead) and **Daniel**
(engineer) both work at the fictional company **Atlas Labs**, discussing the
launch of **Project Atlas** next quarter. The only outside company mentioned
is the fictional vendor **Acme Corp**. No real people, companies, or products
are referenced.

- Length: 414 words, ~3:09 spoken (target: ~380–450 words / ~3 minutes)
- Speakers: `Speaker 0` = Ana, `Speaker 1` = Daniel (see `speakers.json`)
- Five obvious commitments are embedded, spread through the call, one per
  Overheard action kind, in this order:

| # | ~Time | Kind | What happens |
|---|-------|------|--------------|
| a | 0:20 | `create_task` | Ana asks Daniel to send her the Q3 architecture diagram today; he agrees. |
| b | 0:55 | `schedule_followup` | They agree to a 30-minute follow-up next Tuesday at 10. |
| c | 1:30 | `draft_message` | Daniel says he'll post a summary of today's decisions in the team chat after the call. |
| d | 2:05 | `create_doc` | Ana asks for a one-page rollout plan doc by Friday. |
| e | 2:40 | `lookup` | Someone wonders what Acme Corp charges for their enterprise tier and asks to look it up. |

Everything else in the call is realistic filler (status check-ins, a retry-logic
concern, hiring news, rollout phasing) with no actionable commitment attached —
this is what the suggestion brain needs to learn to *not* flag.

The exact machine-checkable version of this script is
`meeting-transcript.jsonl` (one JSON object per spoken line, with timestamps).
The five expected suggestions, in the engine's action contract shape, are in
`expected-actions.json`.

---

## Full transcript

**0:00.00 — Ana:** Hey Daniel, thanks for hopping on. Can you hear me okay?

**0:04.49 — Daniel:** Loud and clear. Morning.

**0:06.12 — Ana:** Morning. Quick check-in on Project Atlas before the planning review.

**0:10.20 — Daniel:** Sounds good, solid progress on the ingestion pipeline this sprint.

**0:14.29 — Ana:** How's the service split holding up since last month?

**0:17.96 — Daniel:** Holding up well, no surprises.

> **[MOMENT (a) → create_task]**

**0:20.00 — Ana:** Good to hear. Before we go further, can you send me the Q3 architecture diagram today? I want to walk leadership through it this afternoon.

> **[MOMENT (a) confirmed]**

**0:30.29 — Daniel:** Yeah, no problem. I'll send you the Q3 architecture diagram today, within the hour.

**0:36.06 — Ana:** Perfect. Is it still the three-service split, or did that change?

**0:40.59 — Daniel:** Mostly the same. I added an event bus between the scheduler and notifications.

**0:45.94 — Ana:** Good, that was my worry. Did the load testing numbers come back?

**0:50.88 — Daniel:** Not yet, running overnight. I'll have numbers by tomorrow morning.

> **[MOMENT (b) → schedule_followup]**

**0:55.00 — Ana:** Let's plan a short follow-up once you have those numbers. Thirty minutes, next Tuesday at ten?

> **[MOMENT (b) confirmed]**

**1:04.66 — Daniel:** Tuesday at ten works. I'll block thirty minutes on my calendar.

**1:11.29 — Ana:** Great, I'll send the invite after this call.

**1:16.12 — Daniel:** Also, hiring's looking up. We got a signed offer out to the backend contractor.

**1:24.57 — Ana:** Great news, we needed the extra hands before launch.

> **[MOMENT (c) → draft_message]**

**1:30.00 — Daniel:** Once we wrap up, I'll draft a summary of today's decisions and post it in the team chat so everyone's aligned.

**1:38.65 — Ana:** Perfect, that saves me writing notes later. Keep it high level.

**1:43.18 — Daniel:** Will do. I'm a little worried about the retry logic on the webhook consumer.

**1:48.94 — Ana:** What's the concern?

**1:50.18 — Daniel:** If Atlas Labs' partners send duplicate events during a retry storm, we could double-process a task.

**1:56.76 — Ana:** Can we add idempotency keys before launch?

**1:59.65 — Daniel:** Yeah, small change. I can have it in by end of next week.

> **[MOMENT (d) → create_doc]**

**2:05.00 — Ana:** Separately, for the executive review, I need a one-page rollout plan. Can you have a draft by Friday?

> **[MOMENT (d) confirmed]**

**2:14.26 — Daniel:** Friday works. I'll put together a one-pager covering scope, timeline, and risks.

**2:20.44 — Ana:** That's exactly what I need. Bullet points, nothing fancy.

**2:25.07 — Daniel:** I'll loop in design too, so it matches the onboarding screens.

**2:30.74 — Ana:** Good call. Still on track for existing customers first?

**2:35.37 — Daniel:** Yes. Phase one existing customers, phase two new signups.

> **[MOMENT (e) → lookup]**

**2:40.00 — Ana:** One more thing. Does anyone know what Acme Corp charges for their enterprise tier? I keep hearing they're pricier than us.

> **[MOMENT (e) confirmed]**

**2:48.48 — Daniel:** Not off the top of my head. Want me to look up Acme Corp's enterprise pricing after the call?

**2:56.18 — Ana:** Yes please, that'd help the pricing deck.

**2:59.28 — Daniel:** Will do. That's everything from me.

**3:01.98 — Ana:** Agreed, this was productive. Thanks, Daniel.

**3:04.69 — Daniel:** Anytime. Diagram's on its way.

**3:07.02 — Ana:** Sounds great, talk soon.

**3:08.95 — Daniel:** Bye.
