# Hackathon brief (summarized from req.md)

**Event:** "Agents, Everywhere: Bots, Channels & More" — AI Tinkerers global hackathon with OpenAI.
**Date:** Saturday Sept 12, 2026, 10:00–17:00 local (Mexico City chapter). One global submission pool, no local judging.

## The challenge (one line)

> Build a working agent for a place people already work, talk and live, and make it meaningfully more useful *because of that context*.

Agents should stop waiting in a separate chat window and show up inside the tools, channels, devices and environments where the work already happens. Example homes: at work (Slack, Teams, email, docs, calendars, tickets, live collaboration), in your pocket (messaging, mobile, notifications), on the web (browse, research, transact), in the room (voice, vision, wearables).

**Our angle:** the meeting *is* the room. The agent lives inside live meetings, listens, and turns what people say into actions executed by agents in the tools the team already uses, with human approval.

## Timeline that matters

| Time | What |
|---|---|
| 10:30–11:00 | Global opening + starter-kit walkthrough |
| 11:15–15:30 | Build (4h15m) |
| 15:30–16:00 | Submit in portal (hard stop) |
| 16:00–16:45 | Optional local show-and-tell |

## Submission checklist (all five required)

1. **Title**
2. **Written description**: what you built, who it is for, why the context matters
3. **Public GitHub repo**: working code that can be reviewed and learned from
4. **Two-minute video**: concise demo of the project in action
5. **Social post** tagging the sponsors

Guiding rule from the organizers: *"A sharp, working demo beats a broad concept."*

## Judging

Global review of every eligible project. Rubric and prize categories to be shared before the event (not in req.md). Design for: working demo, clear context fit, reviewable code, sponsor tech used well.

## Prizes

| Place | Prize |
|---|---|
| 1st | $10k OpenAI credits, Mac mini per member, $1k Exa credits |
| 2nd | $5k OpenAI credits, Ray-Ban Meta glasses per member, $500 Exa credits |
| 3rd | $2.5k OpenAI credits, LOOI robot per member, $250 Exa credits |
| Best use of Ambiguous AI | NVIDIA DGX Spark |
| Best use of CopilotKit | Purple AirPods Max per member |

The two sponsor prizes are the most winnable targets for a single team: they reward depth on one tool rather than beating the whole global pool.

## Sponsors and how each maps to a meeting assistant

You do not need to use every tool. Pick what makes the idea better.

| Sponsor | What they offer | Role in our demo |
|---|---|---|
| **OpenAI** (title sponsor) | Models, Agents SDK, Realtime/transcription APIs, starter kit + credits | Reasoning + action-suggestion brain; possibly live transcription |
| **CopilotKit** (prize) | Agentic app platform: in-app actions, generative UI, real-time shared state, AG-UI / MCP / A2A | The in-app "suggested actions" panel with approve/reject, generative UI cards rendered from agent state |
| **OpenRouter** | AI gateway, hundreds of models, routing and fallback | Model routing: cheap model for classification, strong model for drafting; vendor-neutral |
| **Exa** | Neural web search API for agents | "Look this up" actions: research a person, company, or topic mentioned in the meeting |
| **Trigger.dev** | Open-source background jobs: long-running tasks, retries, realtime, human-in-the-loop waits | Executes approved actions as durable background jobs; waits for approval tokens |
| **Auth0** (already in our project) | Identity for web, mobile and AI agents; agent access to third-party APIs on the user's behalf | Login + agents acting as the user in Calendar/Email/Slack with scoped, consented tokens |
| **Mozilla.ai** | Open-source tooling for trustworthy, controllable AI apps | Open, swappable agent/LLM layer; guardrails; local or low-level runtime piece |
| **Ambiguous AI** (prize) | Workspace of 17 apps (Docs, Mail, Chat, Sheets, CRM, Calendar…) where AI coworkers have identities; CLI + MCP | Where the actions land: the meeting agent is a coworker that files tasks, drafts docs and mails, and posts in chat |

Other sponsors (Ziora Copilot, CETIEM, Andela, Experis) are local/talent sponsors with no developer surface listed. Tag them in the social post.

## What "good" looks like for us

- A live meeting produces a live transcript; the agent surfaces 2–4 concrete suggested actions during the call.
- Each suggestion is a card the user can approve in one click. Approved ones run as background jobs that touch real tools.
- The result is visible where the team works (a task, a doc, a calendar invite, a chat message), not in a chat window.
- Code in the public repo is a clean subset: capture, transcript, suggest, approve, execute. Internal tooling stays out.
