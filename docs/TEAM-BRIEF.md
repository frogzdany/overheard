# Overheard: the meeting agent that gets things done

*Team brief for the "Agents, Everywhere" hackathon, Sept 12, 2026. Read this in 5 minutes, then we split the work.*

---

## 1. The idea

Every meeting produces promises: "I'll send you the diagram", "let's follow up Thursday", "someone check what Acme charges". Most of them evaporate the moment the call ends.

**Overheard is an agent that lives inside the meeting.** It listens to the audio on your Mac, transcribes it live, and while people are still talking it proposes concrete actions it overheard. You approve a card with one click, and a background agent does the work as a real AI coworker inside the workspace your team already uses. Every action is attributed, auditable, and reversible before it runs.

The hackathon theme is "build an agent for a place people already work, talk and live, and make it more useful because of that context". The meeting *is* the room. The agent acts on what was actually said, and the results land where the team works, not in a chat window.

### What the user sees

1. Log in, start a session, pick the app to listen to (Zoom, Teams, Chrome).
2. A live transcript with speakers scrolls on the left.
3. Cards appear on the right as commitments are spoken: **Create task**, **Schedule follow-up**, **Draft message**, **Look this up**. Each shows the reason and the exact quote it came from.
4. Edit the pre-filled fields if needed. Approve or reject.
5. Approved cards run in the background. The card shows "running" then "done" with a link to the created task, event, doc or message.

---

## 2. What we already have (and what we don't)

I have been building a private macOS meeting assistant for a few months. We are bringing a clean subset of it as a starting point, published fresh as the public hackathon repo.

**Already working, we copy it in:**

- System-audio capture scoped to one app (Swift, ScreenCaptureKit).
- Live transcription with speaker separation (Deepgram, two streams, self-healing reconnect).
- A Python engine that streams transcript events over a local WebSocket.
- A Next.js dashboard with a polished live transcript view and Auth0 login.
- A tested "suggest, dedupe, dismiss" pattern from an earlier feature that we reuse for actions.

**Built during the hackathon, now exists end to end, verified keyless:**

- The action suggestion brain (typed actions from the transcript).
- The approval UI cards.
- Background execution of approved actions.
- Connectors to Ambiguous (tasks, docs, calendar, chat) and Exa (lookup), currently exercised
  against mocks.

**What's left, now that the loop exists:**

- Tuning the brain prompt with a real OpenAI key against the expected-actions fixture.
- Running the connectors against a real Ambiguous workspace and Trigger.dev live.
- The two-minute video and the submission form.

That is the honest split, and it goes in the README. Judges reward a sharp working demo and reviewable code, so we say clearly what existed before the hackathon and what we built during the day.

---

## 3. Architecture: ears, brain, hands

Three boxes, one seam between each. Each box can be built and tested alone.

```
 EARS (Python, exists)           BRAIN + UI (Next.js, new)          HANDS (Trigger.dev, new)
 ┌─────────────────────┐        ┌──────────────────────────┐       ┌─────────────────────────┐
 │ Swift audio helper  │  WS    │ Suggestion loop (OpenAI) │ HTTP  │ execute-action task     │
 │ Deepgram live STT   │ ─────► │ CopilotKit action cards  │ ────► │ waits for approval      │
 │ FastAPI + WebSocket │        │ Auth0 login              │       │ runs the connector      │
 └─────────────────────┘        └──────────────────────────┘       │  → Ambiguous AI (MCP)   │
                                                                   │  → Exa (lookup)         │
                                                                   └─────────────────────────┘
```

**The contract between the boxes is one JSON object, the action:**

```jsonc
{
  "id": "a7f3",
  "kind": "create_task | schedule_followup | draft_message | create_doc | lookup",
  "title": "Send Ana the Q3 architecture diagram",
  "rationale": "Ana asked for it and you said you'd send it today",
  "evidence": ["…verbatim transcript quote…"],
  "confidence": 0.82,
  "tool": "ambiguous.tasks.create",
  "args": { "title": "…", "assignee": "…", "due": "2026-09-15" },
  "status": "suggested | approved | running | succeeded | failed | rejected | expired"
}
```

If you know this object, you can work on any box without waiting for the others.

---

## 4. How each sponsor technology fits

We do not bolt on logos. Each sponsor owns one distinct piece, and each gets a visible moment in the demo.

| Sponsor | What it owns in Overheard | The demo moment | Priority |
|---|---|---|---|
| **OpenAI** | The brain. A structured-output call turns the last minute of transcript plus the known actions into new typed actions. | Cards appearing while people talk. | Must |
| **CopilotKit** | The whole human surface. Transcript and actions are shared readable state; every action kind is a `useCopilotAction` with `renderAndWaitForResponse`, so the agent literally pauses until you answer the card. There is a "Best use of CopilotKit" prize for exactly this pattern. | Approve, edit, reject a card. | Must |
| **Ambiguous AI** | Where the work lands. Overheard is provisioned as an AI coworker with its own identity. Approved actions become tasks, docs, calendar events and chat posts via their MCP server. There is a "Best use of Ambiguous AI" prize. | Open the workspace, the task is there, authored by the Overheard coworker. | Must |
| **Trigger.dev** | Durable execution. One background task per action. It parks on a waitpoint until the card is approved, then runs the connector with retries, and streams status back. | Their dashboard shows the run waiting, then completing. | Must |
| **Auth0** | Who the human is. Login already works. Every approval is stamped with the Auth0 user. Stretch: a phone push approval (CIBA) for the one action that leaves the workspace, sending mail. | Login, and the audit line on each action. | Must (login), stretch (CIBA) |
| **Exa** | The "look this up" action. One call to their answer endpoint returns a cited answer that we write into a doc and post in chat. | "Look up Acme's pricing" resolves into a note with sources. | Should |
| **Mozilla.ai** | Open, swappable model layer. `any-llm` powers the rolling summary in the Python engine, `any-guardrail` screens drafted text before it reaches a card. | A guardrail-blocked example in the README. | Should |
| **OpenRouter** | Resilience. Provider fallback for the suggestion call, and a free model as the cheap "is this sentence actionable" prefilter. | Flip a flag, swap the model. | Stretch |

Local sponsors (Ziora Copilot, CETIEM, Andela, Experis) have no developer surface. We tag them in the social post.

---

## 5. How we split the work

The suggest-approve-execute loop is built and runs end to end keyless (mock LLM, mocked hands
connectors, replay fixtures). The four streams below now pick up tuning, live integrations, and
submission work, each still testable alone.

| Stream | Owner | Deliverable | Depends on |
|---|---|---|---|
| **A. Ears** | Daniel | Live capture on a real meeting (not just replay), the two-minute video, and the submission form. | Nothing |
| **B. Brain** | | Tune the suggestion prompt with a real OpenAI key against the expected-actions fixture. | An OpenAI key |
| **C. Cards** | | Polish the action cards and the CopilotKit sidebar against a real key. | An OpenAI key |
| **D. Hands** | | Run the Ambiguous connector against a real workspace, and Trigger.dev live with `EXECUTOR=trigger`. | Ambiguous and Trigger.dev keys |

**Integration checkpoints:** each stream validates independently against the existing keyless
loop; from there we record the two-minute video, write the description and the social post, and
submit.

---

## 6. Accounts and keys we need before 11:15

Everyone should have these in a local `.env.local`, never committed:

- OpenAI API key
- Deepgram API key (I have one)
- Ambiguous workspace and coworker key: `npx ambiguous auth signup --name "Overheard"` takes seconds
- Trigger.dev project (free tier)
- Exa API key (free credits on signup)
- Auth0 domain, client id, audience (I share the dev tenant values)
- OpenRouter key (stretch)

---

## 7. Rules for the public repo

- Fresh repo, one initial commit. No history from the private project.
- No real names, client names, account ids or tenant values in any tracked file. Grep before pushing.
- `.env.example` with placeholders only.
- README says what existed before today and what we built today.

---

## 8. The two-minute video, in one line each

Problem. Login and start listening. Transcript scrolls. Cards appear with quotes. Edit one, approve one, reject one. Trigger.dev run wakes up. The task shows up in Ambiguous, authored by the coworker. Architecture slide with the sponsor logos on the boxes. Repo link.
