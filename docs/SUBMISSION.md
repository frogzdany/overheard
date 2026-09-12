# Overheard: draft submission package

Event: "Agents, Everywhere: Bots, Channels & More," AI Tinkerers global hackathon with OpenAI, Sept 12, 2026.

## 1. Title

Options:

1. Overheard: the meeting agent that gets things done
2. Overheard: meetings that file their own follow-ups
3. Overheard: turn what was said into what got done

**Picked: Overheard: the meeting agent that gets things done**

## 2. Description (submission form)

Overheard is a macOS agent that sits inside a live meeting instead of a separate chat window. It listens to the meeting's audio, transcribes it with speakers, and every 45 seconds proposes concrete actions it heard: create a task, schedule a follow-up, draft a message, create a doc, or look something up, each with a rationale and the exact quote it came from. The user edits, approves, or rejects a card. Approved actions run as durable background jobs and land as real, attributed items in a shared workspace under the Overheard coworker identity.

It is for teams whose meetings generate commitments that usually evaporate the moment the call ends. The meeting is what makes the agent useful: because it hears exactly what was promised and to whom, its suggestions come with evidence instead of guesswork.

Before today we had audio capture, Deepgram live transcription, a Python engine and WebSocket, and a Next.js transcript view with Auth0 login, carried over from a private project. Everything agentic was built today: the action-suggestion brain, the approval cards, and execution.

OpenAI's structured output drives the suggestion brain. CopilotKit provides the sidebar, shared state, and the generative approval cards. Ambiguous AI is where approved actions land, authored by the Overheard coworker. Trigger.dev runs each approval as a durable job with a waitpoint. Auth0 stamps every approval with the logged-in user. Exa answers "look this up" actions with citations. Mozilla.ai's any-llm runs the brain against OpenAI, with OpenRouter as a fallback provider.

(246 words.)

## 3. Two-minute video shot list

| # | Timecode | On screen | Spoken line |
|---|---|---|---|
| 1 | 0:00-0:08 | Cold open: a meeting ending, someone says "I'll send that over," then silence, no follow-up | "Every meeting produces promises. Most of them evaporate the moment the call ends." |
| 2 | 0:08-0:14 | Auth0 login screen, user signs in | "Overheard logs in as you, and every action it takes stays attributed to you." |
| 3 | 0:14-0:20 | Session start screen, picking the app to capture (Zoom window) | "Point it at the meeting. That's the whole setup." |
| 4 | 0:20-0:30 | Live transcript scrolling with speaker labels during the test clip | "It's listening and transcribing with speakers, live." |
| 5 | 0:30-0:42 | ActionsTab: cards appear one by one, each showing rationale and the verbatim quote | "Every 45 seconds it proposes what it just heard: a task, a follow-up, a doc, a lookup." |
| 6 | 0:42-0:50 | Inline edit on one card's field (assignee or due date) | "You edit the pre-filled details before anything runs." |
| 7 | 0:50-0:56 | Approve button clicked on one card, status flips to running | "Approve, and it becomes a real background job." |
| 8 | 0:56-1:02 | Reject button clicked on a different card, card dismisses | "Reject, and it's gone. Nothing runs without a yes." |
| 9 | 1:02-1:12 | Trigger.dev dashboard: run parked at "awaiting approval," then completing after approval | "Trigger.dev holds the job at a waitpoint until you approve it, then runs it with retries." |
| 10 | 1:12-1:22 | Ambiguous workspace: the new task/doc, author field showing "Overheard" | "The result lands in the workspace, authored by Overheard as a real coworker, not a webhook." |
| 11 | 1:22-1:34 | CopilotKit sidebar: user types "create a task for the diagram," a card renders inline and gets approved | "The sidebar isn't just chat. Ask it for something, and the same approval card renders right there." |
| 12 | 1:34-1:46 | Architecture slide: Ears / Brain+UI / Hands boxes with sponsor logos placed on each | "Ears capture and transcribe, the brain proposes with OpenAI through any-llm, the hands execute through Trigger.dev, Ambiguous, and Exa." |
| 13 | 1:46-1:54 | Quick cut: OpenRouter flag flip in a config file, no visible behavior change | "Swap the model provider, nothing else changes." |
| 14 | 1:54-2:00 | Repo URL on screen, README open | "Code's public. Repo link is right here." |

## 4. Social post

### X (under 280 characters)

> Overheard listens to your meeting and turns what got said into tasks, docs & messages, with approval. #AgentsEverywhere with OpenAI, CopilotKit, Ambiguous AI, Trigger.dev, Auth0, Exa, Mozilla.ai, OpenRouter, AI Tinkerers, Ziora Copilot, CETIEM, Andela, Experis.

(261 characters.)

### LinkedIn

> We spent today's AI Tinkerers "Agents, Everywhere" global hackathon (with OpenAI) building Overheard: an agent that sits inside a live meeting instead of a separate chat window.
>
> It listens to the meeting's audio, transcribes it with speakers, and every 45 seconds proposes concrete actions it heard: a task, a follow-up, a drafted message, a doc, a lookup, each with the exact quote it came from. You edit, approve, or reject. Approved actions run as durable background jobs and land as real, attributed work in the team's workspace under Overheard's own coworker identity.
>
> What made this possible in one afternoon: OpenAI for the suggestion brain, CopilotKit for the sidebar, shared state, and the approval cards, Ambiguous AI as the workspace the actions land in, Trigger.dev for durable job execution with human-in-the-loop waitpoints, Auth0 for login and attribution, Exa for cited lookups, and Mozilla.ai's any-llm with an OpenRouter fallback underneath the brain.
>
> Thanks to AI Tinkerers for running this, and to local sponsors Ziora Copilot, CETIEM, Andela, and Experis.
>
> Repo link in comments.

## 5. Prize angles

### Best Use of CopilotKit

- Every action kind (create task, schedule follow-up, draft message, create doc, lookup) is a `useCopilotAction` with `renderAndWaitForResponse`, so the agent's execution literally pauses on the card until a human answers it.
- Transcript and proposed actions are shared readable state between the Python engine and the CopilotKit sidebar, so the copilot always reasons over what actually happened in the meeting, not a stale snapshot.
- The sidebar is not narration-only: typing "create a task for the diagram" into the CopilotKit chat produces the same generative-UI approval card inline, so chat and the meeting feed both drive the identical approval flow.

### Best Use of Ambiguous AI

- Overheard is provisioned as a real AI coworker with its own identity in the workspace (`npx ambiguous auth signup --name "Overheard"`), so every item it creates is attributed to a named coworker, not a service account.
- Approved actions land as real workspace objects through the Ambiguous MCP server, tasks, docs, calendar events, and chat messages, exercising multiple apps in the same workspace from one agent.
- The audit trail runs end to end: an item in Ambiguous shows it was authored by the Overheard coworker off a specific approved action, and that action is itself stamped with the Auth0 user who approved it and the verbatim quote it came from.

## 6. Pre-submit checklist

- [ ] Repo is public on GitHub, fresh history, no private-project commits.
- [ ] README states what existed before today vs. what was built today.
- [ ] `.env.example` committed with placeholders only; no real key ever committed.
- [ ] Privacy grep run across tracked files: no real names, client names, account ids, or tenant values.
- [ ] Two-minute video recorded, under the time limit, uploaded, link works when logged out.
- [ ] Social post published (X and/or LinkedIn) tagging all required sponsors; link saved for the form.
- [ ] Submission portal form filled: title, description, repo link, video link, social post link.
- [ ] Submitted before the 15:30 hard stop (buffer to 15:45 per team plan).
