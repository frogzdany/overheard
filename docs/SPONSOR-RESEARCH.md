# Sponsor Technology Research — "Agents, Everywhere: Bots, Channels & More" (AI Tinkerers x OpenAI, 2026-09-12)

**Project:** Meeting Assistant — a desktop app that captures meeting audio in real time, transcribes it, and runs an agent that *listens* to the meeting and *proactively suggests actions* ("create a task," "draft an email," "schedule a follow-up," "look this up"). Suggested actions are executed by background agents/jobs **only after human approval**, calling external tools (calendar, email, chat, task trackers, web search).

This report was compiled by parallel research agents hitting each sponsor's current (2025–2026) official docs, blogs, and changelogs. Anything that could not be directly verified is explicitly flagged in each section's "Could not verify" notes — treat those as things to double-check live at the hackathon, not as confirmed facts.

---

## 0. Hackathon Starter Kit / Rubric — What We Found

Direct confirmation from the event page (`nyc.aitinkerers.org/p/agents-everywhere-beyond-the-chatbot-global-hackathon-with-openai`, mirrored on `toronto.aitinkerers.org` and `montreal.aitinkerers.org`):

- **No public starter repo was found pre-event.** The published agenda reserves **10:30–11:00am for a "global opening and starter-kit walkthrough"** — the kit appears to be distributed live on the day, not published in advance on GitHub.
- **Sponsors confirmed:** OpenAI (marquee), CopilotKit, OpenRouter, Exa, Trigger.dev, Auth0, Mozilla.ai, Ambiguous AI, Google Cloud Run, Veris AI. Explicit organizer note: **"you do not need to use every tool in the stack."**
- **Prizes:**
  - 1st: $10,000 OpenAI API credits + Mac mini + $1,000 Exa credits
  - 2nd: $5,000 OpenAI API credits + Ray-Ban Meta glasses + $500 Exa credits
  - 3rd: $2,500 OpenAI API credits + LOOI Robot + $250 Exa credits
  - **Best Use of CopilotKit:** AirPods Max (per team member)
  - **Best Use of Ambiguous AI:** NVIDIA DGX Spark
- **Submission requirements:** title + description, public GitHub repo with working code, a 2-minute demo video, a social post tagging sponsors. General guidance: "a sharp, working demo beats a broad concept."
- **No formal, itemized judging rubric (weighted criteria) for this specific event was found** — the aitinkerers.org global hackathon page and a judging-criteria subpage both returned 403 on fetch. A structurally similar past AI Tinkerers event used Running Code 25% / Innovation 25% / Real-World Impact 25% / Theme Alignment 25% — **this is NOT confirmed as this event's rubric**, only a plausible pattern from a similar event. Treat as unverified.
- Framing from the event copy: build agents for places people already work/talk/live (Slack/Teams/email/calendar, messaging, browser, voice/vision/physical) rather than "another chatbot" — this squarely matches the meeting-assistant concept.

**Could not verify:** exact per-sponsor bounty terms beyond CopilotKit/Ambiguous AI prizes above; any baseline free-API-credit grant to *all* entrants (only top-3 prize credits were confirmed); a written rubric with weighted scoring criteria for this exact event.

---

## 1. OpenAI

### What it is / current flagship offerings (2025–2026)
- **Agents SDK** — official framework for building tool-using, multi-agent systems, built on the Responses API. Python package `openai-agents` (PyPI, latest `0.22.0`, Aug 2026), TypeScript package `@openai/agents`. Core concepts: `Agent`, `Runner`/`run()`, tools (`@function_tool` in Python, `tool()` in TS), **handoffs** (agent-to-agent delegation), **guardrails** (parallel input/output validation), **sessions** (built-in memory), tracing, plus Realtime/Voice and Sandbox agent variants.
- **Human-in-the-loop is a first-class primitive**: a tool can declare `needsApproval: true` (or an async predicate); execution pauses and returns an "interruption" that the caller must approve/reject before resuming — this maps almost 1:1 onto our suggest→approve→execute loop. Docs explicitly leave persistence/policy to the app. ([openai.github.io/openai-agents-js/guides/human-in-the-loop](https://openai.github.io/openai-agents-js/guides/human-in-the-loop/), [developers.openai.com/api/docs/guides/agents/guardrails-approvals](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals))
- **Background mode** on the Responses API — long-running jobs without HTTP timeouts, poll for completion. ([developers.openai.com/api/docs/guides/background](https://developers.openai.com/api/docs/guides/background))
- **Realtime API**: speech-to-speech flagship is **`gpt-realtime-2.1`** (low-latency, barge-in, WebRTC/WebSocket, ephemeral client secrets). For **transcription specifically**, OpenAI now splits models by use case: **`gpt-live-transcribe`** for live mic/call streams (this is our meeting-capture model) and **`gpt-transcribe`** for completed recordings — both take richer `prompt`/`keywords`/`languages` params for domain accuracy (e.g., feeding attendee names/jargon). ([developers.openai.com/api/docs/guides/realtime](https://developers.openai.com/api/docs/guides/realtime), [developers.openai.com/api/docs/guides/transcription](https://developers.openai.com/api/docs/guides/transcription)) Community sources also mention `gpt-realtime`, `gpt-realtime-mini`, `gpt-realtime-1.5`, `gpt-realtime-2`, `gpt-realtime-translate`, and retirement of the older `gpt-4o-transcribe` family — **unverified against a primary OpenAI page in this pass; re-check the live model index before quoting.**
- **Responses API** is "recommended for all new projects" over Chat Completions (which is *not* deprecated); the older, separate **Assistants API was fully sunset Aug 26, 2026**. Responses uses typed "Items," native multi-tool orchestration in one call, server-persisted state (`store: true`), and **native hosted tools**: Web Search, File Search, Computer Use, Code Interpreter, and **remote MCP servers** — the model can call these plus custom functions in a single request. ([developers.openai.com/api/docs/guides/responses-vs-chat-completions](https://developers.openai.com/api/docs/guides/responses-vs-chat-completions), [developers.openai.com/api/docs/deprecations](https://developers.openai.com/api/docs/deprecations))
- **Latest models (Sept 2026, per developers.openai.com/api/docs/models — fetched via summarization, re-verify exact pricing before quoting):** **GPT-6 Astra** (flagship reasoning, ~1.05M context); **GPT-5.6 family** — Sol / Terra / Luna (flagship/balanced/budget tiers); audio/voice: GPT-Live 1, GPT-Realtime-2.1, GPT-Realtime-Translate, GPT-Transcribe. **OpenAI DevDay 2026 is Sept 29, San Francisco** — after this hackathon, so no new announcements from it apply yet.
- **AgentKit** (2026): Agent Builder (visual canvas), ChatKit (embeddable chat UI), Connector Registry, Evals — note secondary-source claims that **Agent Builder and Evals will be wound down Nov 30, 2026**, leaving ChatKit as the persisting piece (unverified beyond one secondary blog). **Apps SDK** — build interactive components/actions that run inside ChatGPT conversations, built on MCP; strongly aligned with the hackathon's "bots, channels" theme. ([openai.com/index/introducing-agentkit](https://openai.com/index/introducing-agentkit/), [openai.com/index/introducing-apps-in-chatgpt](https://openai.com/index/introducing-apps-in-chatgpt/))

### SDK / package / snippet
Python: `pip install openai-agents`. TypeScript: `npm install @openai/agents`.

```python
from agents import Agent, Runner, function_tool

@function_tool
def create_task(title: str, due_date: str) -> str:
    """Create a follow-up task from the meeting."""
    return f"Created task '{title}' due {due_date}"

agent = Agent(
    name="MeetingAssistant",
    instructions="You listen to meeting transcripts and propose one concrete action.",
    tools=[create_task],
)
result = Runner.run_sync(agent, "Ana said she'll send the proposal by Friday.")
```

```typescript
import { Agent, run, tool } from '@openai/agents';
import { z } from 'zod';

const createTask = tool({
  name: 'create_task',
  description: 'Create a follow-up task from the meeting',
  parameters: z.object({ title: z.string(), dueDate: z.string() }),
  needsApproval: true, // pauses for human approval before executing
  execute: async ({ title, dueDate }) => `Created task "${title}" due ${dueDate}`,
});
const agent = new Agent({ name: 'MeetingAssistant', tools: [createTask] });
const result = await run(agent, 'Ana said she will send the proposal by Friday.');
```

**Free tier / credits:** No confirmed baseline free-credit grant for all entrants; the top-3 prizes include $2.5k–$10k in OpenAI credits (see §0).

### Fit for meeting assistant
| Pipeline stage | OpenAI piece |
|---|---|
| Audio capture → transcription | Realtime API, `gpt-live-transcribe` over WebSocket |
| Suggestion generation | Responses API (GPT-5.6 Terra/Sol) via an Agents SDK `Agent`, using native MCP/hosted tools for context |
| Action proposal | Agent tool calls (`create_task`, `draft_email`, `schedule_followup`, `look_this_up`) defined with `needsApproval: true` |
| Approval | Agents SDK human-in-the-loop interruption/resume flow |
| Execution | Background mode, or hand off to Trigger.dev (see §5) |

### What would impress them
Lean on the newest, most "agentic" primitives by name: native MCP + hosted tools inside Responses, the Agents SDK's built-in approval/interruption flow (don't reinvent it with custom polling), and Background mode for long jobs. The Apps SDK / "apps in ChatGPT" direction (bots inside channels, built on MCP) is very on-theme for "Bots, Channels & More" if there's time to add a ChatGPT-surface companion.

### Could not verify
- No published starter repo or written judging rubric for this specific event (appears to be given out live).
- Exact retirement dates / fuller realtime model list beyond `gpt-realtime-2.1`, `gpt-live-transcribe`, `gpt-transcribe` — secondary sources only.
- Exact GPT-6 Astra / GPT-5.6 pricing and context-window figures (summarized fetch, not manually re-read).
- AgentKit's Agent Builder/Evals wind-down date (Nov 30, 2026) — single secondary source.

**Key docs:** [developers.openai.com/api/docs/guides/agents-sdk](https://developers.openai.com/api/docs/guides/agents-sdk) · [github.com/openai/openai-agents-python](https://github.com/openai/openai-agents-python) · [github.com/openai/openai-agents-js](https://github.com/openai/openai-agents-js) · [developers.openai.com/api/docs/guides/realtime](https://developers.openai.com/api/docs/guides/realtime) · [developers.openai.com/api/docs/guides/transcription](https://developers.openai.com/api/docs/guides/transcription) · [developers.openai.com/api/docs/guides/responses-vs-chat-completions](https://developers.openai.com/api/docs/guides/responses-vs-chat-completions) · [developers.openai.com/api/docs/models](https://developers.openai.com/api/docs/models)

---

## 2. CopilotKit

### What it is / current flagship offerings
CopilotKit ("the Agentic Application Platform" / "the Frontend Stack for Agents & Generative UI") is an open-source (MIT) React-first framework for embedding AI copilots/agentic UI directly into apps (web, mobile, Slack, Teams). Flagship pillars: **AG-UI protocol**, **CoAgents** (shared state), **Generative UI**, **human-in-the-loop workflows**, persistent **Rich Threads** (Copilot Cloud). 2026 additions: **WebMCP** support (frontend tools callable by browser AI agents like ChatGPT Atlas/Comet/Dia), **MCP Apps** (MCP servers shipping interactive UI), **OpenBot** (Slack/Teams bot framework), **AIMock** (mocks the full agentic call chain for testing), **Pathfinder** (self-hosted MCP knowledge server). CopilotKit raised a $27M Series A. ([copilotkit.ai/blog/series-a](https://www.copilotkit.ai/blog/series-a), [MarkTechPost, May 2026](https://www.marktechpost.com/2026/05/21/how-copilotkit-is-redefining-the-agentic-ai-stack-in-2026/))

**AG-UI protocol**: open, event-based standard (~16 event types) for streaming agent execution state (messages, tool calls, state patches, interrupts) to a frontend over SSE/WebSockets. Official/partner framework support: **LangGraph, CrewAI, Mastra, Pydantic AI, Agno, LlamaIndex, AG2, AWS Strands Agents, Google ADK, Microsoft Agent Framework**. Community: Claude Agent SDK, Langroid. **OpenAI Agents SDK is listed as "in progress"** on the AG-UI GitHub repo — a secondary blog claims broader compatibility, but no official `docs.copilotkit.ai` OpenAI-Agents-SDK quickstart page was found (direct fetch 404'd). Treat OpenAI Agents SDK support as unofficial/DIY for now. ([docs.copilotkit.ai/agentic-protocols/ag-ui](https://docs.copilotkit.ai/agentic-protocols/ag-ui), [github.com/ag-ui-protocol/ag-ui](https://github.com/ag-ui-protocol/ag-ui))

Verified official quickstarts: **LangGraph** (Python & TS, `docs.copilotkit.ai/langgraph-python`), **Mastra** (`docs.copilotkit.ai/mastra/quickstart`, also mirrored in Mastra's own docs, starter repo `github.com/CopilotKit/with-mastra`), plus CrewAI, Google ADK, Pydantic AI, Claude Agent SDK.

### SDK / packages / language support
npm packages: `@copilotkit/react-core`, `@copilotkit/react-ui`, `@copilotkit/runtime` (framework-agnostic backend), `@copilotkit/runtime-client-gql`, `@copilotkit/core`, `@copilotkit/react-native`, `@copilotkit/vue`, `@copilotkit/sdk-js`. **Not JS/TS-only**: Python backend agents (LangGraph, CrewAI, Pydantic AI) are fully supported over AG-UI/Copilot Runtime; a `sdk-python` exists in the monorepo.

**In-app action:**
```tsx
useCopilotAction({
  name: "sayHello",
  description: "Say hello to someone.",
  parameters: [{ name: "name", type: "string", description: "name of the person to greet" }],
  handler: async ({ name }) => { alert(`Hello, ${name}!`); },
});
```

**Human-in-the-loop approval (the critical pattern for us) — `useCopilotAction` + `renderAndWaitForResponse`:**
```tsx
useCopilotAction({
  name: "email_tool",
  parameters: [{ name: "email_draft", type: "string", description: "The email content", required: true }],
  renderAndWaitForResponse: ({ args, status, respond }) => (
    <EmailConfirmation
      emailContent={args.email_draft || ""}
      isExecuting={status === "executing"}
      onCancel={() => respond?.({ approved: false })}
      onSend={() => respond?.({ approved: true, metadata: { sentAt: new Date().toISOString() } })}
    />
  ),
});
```
The agent calls the tool → CopilotKit renders the component and *pauses* → stays mounted until `respond()` is called → the response flows back as the tool result. A second, graph-enforced pattern (`useInterrupt` + LangGraph's `interrupt()`) exists but is **not supported by every backend** — e.g., Mastra's docs literally title the page "Interrupts (Not Supported)," so the tool-based `useCopilotAction` pattern is the more universally portable HITL mechanism.

**Free tier:** Fully open source (MIT), free to self-host entirely. Optional hosted **Copilot Cloud**: free "Developer" tier (1 dev, 3-day thread retention, 200 threads, 1GB storage, 1 Slack/Teams org). Paid tiers from $39/mo. ([copilotkit.ai/pricing](https://www.copilotkit.ai/pricing))

### Fit for meeting assistant
CopilotKit should own the **entire human-facing review/approval surface**, not transcription or reasoning:
- **CoAgents shared state** streams `{transcript_so_far, suggested_actions: [...]}` from the backend agent to the UI live, no polling.
- **Generative UI** renders each suggested action as its own typed card (assignee/due-date fields for a task, a draft body for an email) instead of a chat bubble.
- **`renderAndWaitForResponse`** is the literal implementation of "suggested, not executed": the agent proposes an action as a tool call, the UI blocks on a rendered approval card, and only `respond({approved: true})` triggers the downstream job (Trigger.dev, an API call, etc.).
- In-app actions can also flow user→agent (e.g., `snoozeAction`, `editSuggestion`, `retryLookup`).

### What would impress them
This hackathon has a confirmed **"Best Use of CopilotKit" prize (AirPods Max)**. CopilotKit's own **Generative UI Global Hackathon Starter Kit** ([github.com/CopilotKit/Generative-UI-Global-Hackathon-Starter-Kit](https://github.com/CopilotKit/Generative-UI-Global-Hackathon-Starter-Kit)) is the clearest signal of what they want: durable/resumable threads, an agent-driven live canvas (not just chat), real external-tool integrations (MCP to Notion/Slack/Linear/GitHub), a deliberate mix of generative-UI approaches, and **user control — the agent doesn't execute unsupervised**. That last point is exactly our HITL design. Name-dropping **AG-UI**, **WebMCP**, and **MCP Apps** in the README signals current (not legacy chat-widget) CopilotKit usage.

### Could not verify
- No official OpenAI Agents SDK quickstart page (contradicted by one secondary source).
- Exact judging rubric for "Best Use of CopilotKit" (only the prize was confirmed).
- Some AG-UI multi-language SDK claims (Go/Kotlin/Rust/etc.) come from a secondary source, not the primary GitHub repo table.

**Key docs:** [docs.copilotkit.ai](https://docs.copilotkit.ai/) · [docs.copilotkit.ai/agentic-protocols/ag-ui](https://docs.copilotkit.ai/agentic-protocols/ag-ui) · [github.com/ag-ui-protocol/ag-ui](https://github.com/ag-ui-protocol/ag-ui) · [docs.copilotkit.ai/langgraph-python/human-in-the-loop/interrupt-flow](https://docs.copilotkit.ai/langgraph-python/human-in-the-loop/interrupt-flow) · [github.com/CopilotKit/Generative-UI-Global-Hackathon-Starter-Kit](https://github.com/CopilotKit/Generative-UI-Global-Hackathon-Starter-Kit) · [copilotkit.ai/pricing](https://www.copilotkit.ai/pricing)

---

## 3. OpenRouter

### What it is / current flagship offerings
A **unified API/router across 500+ LLMs from 80+ providers**, exposed through a single OpenAI-compatible endpoint — handles provider selection, failover, and billing so an app doesn't need per-vendor SDKs/keys. OpenRouter is a **confirmed sponsor of this exact hackathon**. ([openrouter.ai/docs/quickstart](https://openrouter.ai/docs/quickstart))

Agent-relevant features (2025–2026):
- **Model routing**: `model: "openrouter/auto"` classifies each prompt into a task type and ranks candidates by trailing community usage, then applies your account's allowed-model/cost-tier restrictions; degrades gracefully rather than erroring, and "sticks" to one model across a session.
- **Provider fallback**: automatic retry on the next provider in an ordered list if one is down/rate-limited — the key live-demo reliability feature.
- **Tool/function calling**: standardized OpenAI-style `tools`/`tool_calls` across nearly all supported models — "write the loop once, swap the model string."
- **Web search plugin**: append `:online` to any model slug (works even on free models) to ground answers in live web results; native passthrough for Anthropic/Google/OpenAI/Perplexity, Exa-powered for everyone else; returns `url_citation` annotations. Configurable via an explicit `web` plugin (`max_results`, `include_domains`, `engine`).
- **Structured outputs**: `response_format: {type:"json_schema", ...}` across OpenAI/Gemini/Anthropic/Fireworks — good for forcing our suggestion schema.
- **Prompt caching**: automatic (OpenAI/DeepSeek/Groq/Gemini) or explicit `cache_control` (Anthropic/Qwen); `session_id` enables sticky routing to maximize cache hits on a growing transcript.
- **Agent SDK (TS, 2026)**: wraps the whole agent loop into one `callModel()` call with auto tool-execution/validation via Zod and built-in stop conditions.
- **Shell tool + Files API (beta, Sept 8 2026)**: hosted sandboxed Linux shell + file I/O for any model, billed per active-second — lets a model run a script server-side (e.g., generate an `.ics` file).
- **Fusion (June 2026)**: sends one prompt to several models in parallel, a judge model synthesizes consensus/contradictions — could sanity-check a proposed action before showing it for approval.

### SDK / package / snippet
Official quickstart pattern is the **OpenAI SDK pointed at a different base URL**:
```python
from openai import OpenAI
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key="<OPENROUTER_API_KEY>")
resp = client.chat.completions.create(
    model="openai/gpt-5.2",
    extra_headers={"HTTP-Referer": "https://your-app-url.example", "X-Title": "Meeting Assistant Hackathon Demo"},
    messages=[{"role": "user", "content": "Suggest one follow-up action from this meeting snippet..."}],
)
```
First-party packages also exist: `@openrouter/sdk` (npm), `@openrouter/ai-sdk-provider` (Vercel AI SDK provider), `pip install openrouter` (Python) — but the OpenAI-SDK trick remains the fastest hackathon path.

**Free tier / credits:** `:free`-suffixed models work with a $0 balance — 20 req/min, 50 req/day (1,000/day after ever purchasing ≥$10 credits). The exact live free-model roster rotates constantly (third-party trackers list ~20 free endpoints as of Sept 2026, e.g. NVIDIA Nemotron 3, Google Gemma 4 — **not independently confirmed against the live model page**). **No official, itemized OpenRouter credit code for this specific event was found**; only sponsor-listing was confirmed — ask organizers directly. Pricing: 0% fee on Free tier, ~5.5% Pay-as-you-go, ~8% Business; BYOK gets $25k/month fee-free inference (Pay-as-you-go/Business) or $200k/month (Enterprise).

### Fit for meeting assistant
Reliability + flexibility layer for the **suggestion-generation LLM call**: route through OpenRouter instead of one vendor's SDK so a mid-demo rate-limit blip on any single provider doesn't kill the flow (automatic provider fallback). Use structured outputs to force `{action_type, payload, confidence, rationale}` JSON for the downstream approval UI. Use the `:online` web-search plugin to implement the **"look this up" action type** with zero extra search-API integration. Prompt caching + `session_id` keep a growing meeting transcript cheap/fast to re-query.

### What would impress them
Namecheck their newest 2026 launches: the **Agent SDK**, the **Shell tool/Files API beta**, and **Fusion** — using the shell tool to actually execute a small script server-side (e.g., building a calendar `.ics` file) or using Fusion to cross-check a hallucination-prone drafted action before approval would be strong, current talking points.

### Could not verify
- Exact free-credit amount/code for this specific hackathon.
- Live `:free` model roster (dynamic page, relied on third-party trackers).
- The path `openrouter.ai/docs/features/tool-calling` 404'd; content reconstructed from `/docs/guides/features/tool-calling` and a tutorial blog post, not a direct fetch of the current guide.

**Key docs:** [openrouter.ai/docs/quickstart](https://openrouter.ai/docs/quickstart) · [openrouter.ai/docs/features/model-routing](https://openrouter.ai/docs/features/model-routing) · [openrouter.ai/docs/features/web-search](https://openrouter.ai/docs/features/web-search) · [openrouter.ai/docs/features/structured-outputs](https://openrouter.ai/docs/features/structured-outputs) · [openrouter.ai/docs/features/prompt-caching](https://openrouter.ai/docs/features/prompt-caching) · [openrouter.ai/blog/announcements/shell-tool](https://openrouter.ai/blog/announcements/shell-tool/) · [openrouter.ai/blog/announcements/fusion-beats-frontier](https://openrouter.ai/blog/announcements/fusion-beats-frontier/) · [openrouter.ai/pricing](https://openrouter.ai/pricing)

---

## 4. Exa

### What it is / current flagship offerings
Exa (YC S21, well-funded — Series B $85M, Series C $250M) is a **neural/semantic search API purpose-built for AI/LLM applications** — "the search engine for AIs" — returning clean, structured, LLM-ready content instead of ranked blue links. ([exa.ai](https://exa.ai/), [exa.ai/blog/announcing-series-c](https://exa.ai/blog/announcing-series-c))

Flagship endpoints:
- **Search** — neural/semantic + keyword search with rich filtering (domains, dates, category); modes `instant`/`fast`/`auto`/`deep-lite`/`deep`/`deep-reasoning`.
- **Contents** — extracts clean text/highlights/summaries from URLs, with live-crawl freshness.
- **Find Similar** — semantically similar pages to a given URL.
- **Answer** (`/answer`) — runs a search internally and returns a direct, cited answer; supports `model` selection (`exa`, `exa-pro`, `exa-research`, `exa-fast`), streaming, structured JSON via `outputSchema`.
- **Research API** (`/research`, June 2025) — agentic, multi-step research: iteratively searches/reads/clusters/synthesizes across sources, async task-based (create task → poll), returns markdown or schema-conforming JSON with citations. Claims 94.9% on SimpleQA ("highest of any research API").
- **Exa Agent** (newest, June 16 2026) — combines frontier LLMs with Exa's search tools for deep research/list-building/entity-enrichment via parallel subagents and cost-optimized model fusion (effort levels $0.012–$1.00/request, or "auto" effort). Backs the `agent_run` MCP tool.
- **Websets** — persistent, structured collections of web entities matching a query (self-updating "smart spreadsheets"), with scheduled **Monitors** pushing live updates via webhook. Less relevant to our one-off "look this up" need, but a good "mature platform" namedrop.

### SDK / package / snippet
JS/TS: `exa-js` (npm). Python: `exa-py` (pip, 3.9+).
```python
# pip install exa-py
from exa_py import Exa
exa = Exa(api_key="YOUR_API_KEY")
results = exa.search("blog post about artificial intelligence", type="auto", contents={"highlights": True})
response = exa.answer("What is the capital of France?")
print(response.answer)
```
```javascript
// npm install exa-js
import Exa from "exa-js";
const exa = new Exa(process.env.EXA_API_KEY);
const response = await exa.answer("What caused the 2008 financial crisis?");
```

**Official MCP server**: `github.com/exa-labs/exa-mcp-server`, exposing `web_search_exa`, `web_fetch_exa`, `agent_run`, `web_search_advanced_exa` to any MCP-compatible host (Claude, Cursor, OpenAI Agents SDK via MCP, etc.):
```json
{ "exa": { "url": "https://mcp.exa.ai/mcp", "headers": { "x-api-key": "YOUR_EXA_API_KEY" } } }
```
or `npx exa-mcp-server` for local/stdio. A separate Websets MCP server also exists (`exa-labs/websets-mcp-server`). No dedicated first-party OpenAI-Agents-SDK/LangChain package was found beyond generic MCP compatibility and raw SDK calls — **unverified/likely doesn't exist as a named package**.

**Free tier / credits:** New signups get **~$20 free credits** (~2,800 basic searches); an ongoing free tier grants **$10 in credits every month** (a third-party tracker claims this was raised to a 20,000 req/month equivalent in July 2026 — **unconfirmed on exa.ai directly**). Pay-as-you-go: Search $7/1k, Deep Search $12/1k, Answer $5/1k, Contents $1/1k pages, Monitors $15/1k. **Confirmed for this exact hackathon**: Exa is a Developer Infrastructure Partner contributing **$1,000 / $500 / $250 in Exa credits** to 1st/2nd/3rd place respectively (see §0).

### Fit for meeting assistant
Exa is the natural engine for the **"look this up" action type** end to end: agent detects a research-worthy mention (competitor name, unfamiliar term) → proposes the action → on approval, a background job calls **Answer** (fast, cited) or **Research** (deeper, multi-source) → the synthesized answer + citations is attached to meeting notes, optionally re-surfaced for approval before being shared onward (e.g., pasted into a Slack message or email draft). A minimal tool:
```javascript
const lookThisUpTool = {
  name: "look_this_up",
  description: "Research a topic, company, or term mentioned in the meeting and return a cited answer.",
  parameters: { topic: "string" },
  execute: async ({ topic }) => {
    const { answer, citations } = await exa.answer(topic);
    return { summary: answer, sources: citations.map(c => c.url) };
  },
};
```
This is a thin, one-HTTP-call integration — low risk to add even late in a hackathon.

### What would impress them
Namecheck **Exa Agent** (their newest, June 2026 flagship) and **Exa Research**'s SimpleQA benchmark claim. Using **Websets Monitors** for something like "track mentions of this competitor across future meetings" would be an ambitious stretch goal showing depth beyond a single search call.

### Could not verify
- Exact free-tier monthly request cap (third-party claim of 20,000/month unconfirmed on exa.ai).
- A "$1,000 startup/education grant program" mentioned only on third-party pricing trackers.
- Any dedicated OpenAI Agents SDK / LangChain first-party package (beyond MCP/raw SDK).
- Precise `/research` create-task JSON schema (docs page redirected inconsistently during fetch).
- An unauthenticated/rate-limited "free MCP tier" (3 QPS/150 calls/day) mentioned only in a secondary source.

**Key docs:** [exa.ai/docs/reference/getting-started](https://exa.ai/docs/reference/getting-started) · [exa.ai/docs/reference/answer](https://exa.ai/docs/reference/answer) · [docs.exa.ai/reference/research/create-a-task](https://docs.exa.ai/reference/research/create-a-task) · [exa.ai/docs/websets/overview](https://exa.ai/docs/websets/overview) · [exa.ai/docs/reference/exa-mcp](https://exa.ai/docs/reference/exa-mcp) · [github.com/exa-labs/exa-mcp-server](https://github.com/exa-labs/exa-mcp-server) · [exa.ai/pricing](https://exa.ai/pricing) · [exa.ai/blog/exa-agent](https://exa.ai/blog/exa-agent)

---

## 5. Trigger.dev

### What it is / current flagship offerings
An **open-source, TypeScript-first durable-execution / background-jobs platform**, explicitly repositioned around AI: GitHub tagline "build and deploy fully-managed AI agents and workflows"; homepage: "the open source platform for durable AI agents." Writes long-running workflows as plain async TS — no timeouts, automatic retries, elastic scaling, built-in queuing. ([github.com/triggerdotdev/trigger.dev](https://github.com/triggerdotdev/trigger.dev), [trigger.dev](https://trigger.dev/))

**Current version: v4 (GA)**, built on "Run Engine 2.0." Package: `@trigger.dev/sdk` (TS/JS only — application code is TypeScript, though the platform repo is polyglot). v4 highlights: **warm starts** (100–300ms vs. several seconds cold start), **waitpoints** (a new primitive that blocks a run until a condition is met — the foundation for human approval), priority-based queueing, native "convert a task into a Vercel AI SDK tool" integration, OpenTelemetry export, official Helm chart.

```typescript
import { task } from "@trigger.dev/sdk";
const myTask = task({
  id: "unique-task-id",
  retry: { maxAttempts: 3, minTimeoutInMs: 500 },
  run: async (payload: { message: string }, { ctx }) => {
    return { success: true };
  },
});
```

### `triggerAndWait` — chaining agent steps
```ts
export const parentTask = task({
  id: "parent-task",
  run: async (payload: string) => {
    const result = await childTask.triggerAndWait("some-data");
    if (result.ok) console.log("Result", result.output);
  },
});
```
(Never wrap multiple `triggerAndWait()` calls in `Promise.all()` — use `batchTriggerAndWait()` for parallel waits instead.)

### `wait.forToken` — the human-approval primitive (critical for us)
Built on v4's waitpoints; a task pauses at zero idle compute cost until an external token is completed via SDK, webhook, or browser call:
```ts
import { wait } from "@trigger.dev/sdk";

const token = await wait.createToken({ timeout: "10m", idempotencyKey: "my-idempotency-key" });
// ... surface token.url / token.publicAccessToken to the approval UI ...

type ApprovalToken = { status: "approved" | "rejected" };
const result = await wait.forToken<ApprovalToken>(token.id);
if (result.ok && result.output.status === "approved") {
  // proceed to call Gmail/Calendar/etc.
}
```
Completion can happen server-side (`wait.completeToken(...)`), via a **browser-safe CORS-enabled REST call using `publicAccessToken`** (ideal for a desktop app's local web UI), or via the token's webhook URL. Docs describe this literally as built "for human-in-the-loop approval workflows... allow a human to reject, suggest changes, or approve."

### Realtime — live status to the frontend
`runs.subscribeToRun(runId)` server-side; `@trigger.dev/react-hooks`'s `useRealtimeRun`/`useRealtimeStream` client-side for live run status + token-by-token streaming (e.g., a drafted email body appearing live).

### Scheduling
Recurring: `schedules.task({ cron: "0 */2 * * *", ... })`. One-off delay (for "schedule a follow-up in 3 days"): `await followUpTask.trigger(payload, { delay: "3d" })` (or an ISO timestamp); reschedulable via `runs.reschedule()`.

### Documented AI-agent patterns
Dedicated guide (`trigger.dev/docs/guides/ai-agents/overview`) covering five patterns from Anthropic's "Building Effective Agents" research (Prompt Chaining, Routing, Parallelization, Orchestrator-Workers, Evaluator-Optimizer), a `chat.agent()` API for durable multi-turn conversations, a full blog post with TS implementations (`trigger.dev/blog/ai-agents-with-trigger`), and an official coding-agent skills repo (`github.com/triggerdotdev/skills`). An example project doing "audio summaries with a human-in-the-loop workflow" via ReactFlow + waitpoint tokens is a close analog to our use case.

### Free tier
| | Free | Hobby ($10/mo) |
|---|---|---|
| Monthly credits | $5 | $10 |
| Concurrent runs | 20 | 50 |
| Concurrent Realtime connections | 10 | — |
| Schedules | 10 | 100 |
| Tasks | Unlimited | Unlimited |

More than sufficient for a one-day hackathon demo.

### Fit for meeting assistant
Trigger.dev owns the **entire background-execution + approval layer**: each suggested action becomes its own `task()` (`createTaskAction`, `draftEmailAction`, `scheduleFollowUpAction`, `lookupAction`); inside the task, `wait.createToken()` + `wait.forToken()` pauses execution until the desktop UI's Approve/Reject click completes the token (via the CORS-safe `publicAccessToken` REST call — no server round-trip from the renderer); `useRealtimeRun`/`useRealtimeStream` drive a live "waiting for approval → executing → done" status in the UI; multi-step actions (e.g., "look this up, then draft an email using the result") chain via `triggerAndWait()`; "schedule a follow-up" is modeled directly as a `delay: "3d"` triggered task. Automatic retries protect a live demo against a flaky Gmail/Calendar API call.

### What would impress them
Use their newest primitives **by name**: waitpoints/`wait.forToken`, Realtime, and the v4 Run Engine warm-start story — this is literally their current flagship human-in-the-loop narrative.

### Could not verify
- Exact case-study URLs for "Pallet"/"Capy" (mentioned only in search snippets).
- Precise v4.x point release / GA date.
- Whether waitpoint behavior differs between Free and paid plans (not explicitly called out on the pricing page).

**Key docs:** [trigger.dev/docs/introduction](https://trigger.dev/docs/introduction) · [trigger.dev/docs/wait-for-token](https://trigger.dev/docs/wait-for-token) · [trigger.dev/changelog/waitpoints](https://trigger.dev/changelog/waitpoints) · [trigger.dev/docs/realtime/overview](https://trigger.dev/docs/realtime/overview) · [trigger.dev/docs/triggering](https://trigger.dev/docs/triggering) · [trigger.dev/docs/tasks/scheduled](https://trigger.dev/docs/tasks/scheduled) · [trigger.dev/docs/guides/ai-agents/overview](https://trigger.dev/docs/guides/ai-agents/overview) · [trigger.dev/pricing](https://trigger.dev/pricing)

---

## 6. Auth0 (Auth for AI Agents / Auth0 for GenAI)

### What it is / current flagship offerings
Auth0's **"Auth for GenAI" ("Auth0 for AI Agents")** went GA in late 2025, built explicitly for apps where an autonomous agent acts on behalf of a logged-in human. Tagline: "Ship agents fast. Without the identity drag." Four pillars, all shipped and GA:
1. **User Authentication** — Universal Login extended to GenAI apps, account linking, step-up auth.
2. **Token Vault** — lets an agent call third-party APIs (Gmail, Slack, GitHub, Google Calendar, etc.) using tokens Auth0 stores/refreshes, without the app touching user credentials.
3. **Asynchronous Authorization (CIBA)** — human-in-the-loop approval for sensitive agent actions, pushed to the user's phone, decoupled from the chat session.
4. **Fine-Grained Authorization (FGA)** — relationship-based access control (built on open-source **OpenFGA**, Apache-2.0, Google-Zanzibar-style) scoping exactly which resources/actions an agent may touch; also used to filter RAG retrieval per-user.

Recent 2026 momentum: **Auth for MCP reached GA in May 2026** (OAuth 2.1/OIDC for MCP servers, CIMD registration, on-behalf-of token exchange); **"Agent as Principal"** (agents get first-class, auditable identities anchored to a verified human); **On-Behalf-Of Token Exchange**; **Token Vault with Organizations support**; **FGA Permissions Index**; **Cross App Access (XAA)** (beta); an **Agent Gateway** for securing MCP access (roadmap/early messaging).

### Token Vault — concrete flow
User logs in via Universal Login → via a "Connected Accounts" flow, redirected to consent with the external provider (e.g., Google) for specific OAuth scopes → Auth0 stores the provider's access+refresh tokens → your backend exchanges its Auth0 session token for the external provider's token via Token Vault (no re-auth, no credential storage in your app) → the agent calls the third-party API directly. **30+ pre-integrated connections** (Google/Workspace, Microsoft/Azure AD, GitHub, Slack, Jira, Salesforce, Dropbox, and more).

```javascript
// Token Vault → Google Calendar access token (Next.js)
import { auth0 } from "@/lib/auth0";
import { google } from "googleapis";

const { token } = await auth0.getAccessTokenForConnection({ connection: "google-oauth2" });
const authClient = new google.auth.OAuth2();
authClient.setCredentials({ access_token: token });
const response = await google.calendar("v3").freebusy.query({
  auth: authClient,
  requestBody: { timeMin, timeMax, timeZone: "UTC", items: [{ id: "primary" }] },
});
```

### Asynchronous Authorization via CIBA — concrete flow (the "real" human approval)
Uses the OpenID **CIBA** standard + **Rich Authorization Requests (RAR)** so the push notification shows exact transaction details: agent backend calls `/bc-authorize` with the user ID + a RAR payload describing the action → gets an `auth_req_id` → polls `/token` → Auth0 pushes a notification via **Auth0 Guardian mobile push** (default; email is a paid Essentials+ fallback) → user approves/denies on their phone → next poll returns tokens and the agent proceeds. Framed by Auth0 as protection even if the agent itself is compromised.

```typescript
// CIBA human-approval-required tool (Vercel AI SDK)
import { Auth0AI } from "@auth0/ai-vercel";
import { AccessDeniedInterrupt } from "@auth0/ai/interrupts";

const auth0AI = new Auth0AI();
export const withAsyncAuthorization = auth0AI.withAsyncAuthorization({
  userID: async () => (await getUser())?.sub,
  bindingMessage: async ({ product, qty }) => `Do you want to buy ${qty} ${product}`,
  scopes: ["openid", "product:buy"],
  audience: process.env.SHOP_API_AUDIENCE!,
  onUnauthorized: async (e) => e instanceof AccessDeniedInterrupt ? "User denied the request" : e.message,
});

export const buyTool = withAsyncAuthorization(tool({
  execute: async (args) => {
    const { accessToken } = getAsyncAuthorizationCredentials()!;
    // call the API with this bearer token only after phone approval
  },
}));
```
A LangGraph variant exposes `auth0AI.withCIBA(...)` / `ciba.protectTool(tool, { scope, binding_message, onApproveGoTo, onRejectGoTo })` with a scheduler that resumes the graph post-approval. Full reference app: `github.com/auth0-samples/auth0-assistant0` (TS-LangChain, TS-Vercel-AI, TS-LlamaIndex, Py-LangChain, Py-LlamaIndex variants).

### SDK / packages
Hub-and-spoke: `@auth0/ai` (JS core) / `auth0-ai` (Python core), with framework adapters `@auth0/ai-vercel`, `@auth0/ai-langchain` (JS — **flagged by Auth0 itself as dev-only, not production-supported**), `@auth0/ai-llamaindex`, `@auth0/ai-genkit` (JS), and `auth0-ai-langchain`, `auth0-ai-llamaindex` (Python — more mature per GA blog). **No dedicated OpenAI Agents SDK package found** (`@auth0/ai-openai` does not appear to exist) — unverified/not found.

### Free tier
Core Auth0: **25,000 MAU free**, no card, no time limit — ample for a hackathon demo. Token Vault and Guardian-push CIBA work on the free tier (email-based CIBA fallback is gated to paid Essentials+). Auth0 FGA: free trial, no stated time cap, community support only; OpenFGA itself is fully free/self-hostable (Apache-2.0). **No published hackathon-specific credit amount found**, but Auth0 is a confirmed sponsor of this exact event — check the local event page/Slack for a bounty.

### Fit for meeting assistant
- **(a) Auth**: Universal Login handles desktop-app sign-in, establishing the verified human identity the agent acts on behalf of.
- **(b) Token Vault (execution)**: on approval, a background job calls `getAccessTokenForConnection({connection: "google-oauth2"})` (or GitHub/Slack) for a short-lived scoped token and calls Gmail/Calendar/Slack APIs directly — no long-lived credentials stored anywhere in our code.
- **(c) CIBA (the actual "human approval")**: wrap sensitive tools (`send_email`, `create_calendar_event`) with `withAsyncAuthorization`/`protectTool` so approval is a **real push notification to the user's phone** via Auth0 Guardian with a RAR message like "Approve: send email to jane@acme.com re: Q3 roadmap?" — materially more impressive and demoable than an in-app button, and it survives the desktop app being closed.
- Optionally layer **FGA** to restrict which calendars/repos/channels a given agent instance may touch, for a "least-privilege agent" story.

### What would impress them
Building the demo as agent listens → proposes action → **CIBA push to phone** → approved → **Token-Vault-scoped** call to Calendar/Gmail is close to Auth0's own reference sample app (`auth0-assistant0`) and directly showcases their current flagship narrative: "Agent as Principal" + CIBA + Token Vault together.

### Could not verify
- Exact hackathon-specific Auth0 credit amount or a formal "Auth0 bounty" prize track (only sponsorship presence confirmed).
- A dedicated OpenAI Agents SDK integration package.
- Production-readiness of `@auth0/ai-langchain` (JS) vs. the Python equivalent.

**Key docs:** Auth0's AI product pages (overview, Token Vault, Asynchronous Authorization introduction and get-started guide, Fine-Grained Authorization) and the `auth0-samples/auth0-assistant0` reference app on GitHub.

---

## 7. Mozilla.ai

### What it is / current flagship offerings
Mozilla.ai ships a family of open-source (Apache-2.0), free, self-hostable Python/Go libraries for building and operating agents, marketed together as the **"Choice-first Stack."** ([mozilla.ai/open-tools/choice-first-stack](https://www.mozilla.ai/open-tools/choice-first-stack))

- **any-agent** (Python, `pip install any-agent`) — unified interface to build/run/compare agents across frameworks (Agno, Google ADK, LangChain, LlamaIndex, OpenAI Agents SDK, smolagents, Mozilla's own TinyAgent), with built-in OpenTelemetry tracing and evaluation. **Now in soft deprecation** — its minimal agent-loop core has been extracted into a newer, leaner package, **`mozilla-ai-tinyagent`** (built on `any-llm`), which is now recommended for a single lean agent loop; `any-agent` remains the right choice specifically when comparing agents *across* frameworks.
  ```python
  from any_agent import AgentConfig, AnyAgent
  from any_agent.tools import search_web, visit_webpage
  agent = AnyAgent.create("tinyagent", AgentConfig(model_id="mistral:mistral-small-latest",
      instructions="Use the tools to find an answer", tools=[search_web, visit_webpage]))
  agent_trace = agent.run("Which Agent Framework is the best??")
  ```
- **any-llm** (Python, `pip install 'any-llm-sdk[mistral,ollama]'`) — unified LLM-provider call interface (OpenAI, Anthropic, Mistral, Ollama, Azure/Foundry, etc.), OpenAI-compatible abstraction, not a hosted gateway. A **Go port (`any-llm-go`)** and a `langchain-any-llm` adapter also exist; Rust/TS/Go/Python SDKs exist for Mozilla.ai's separate commercial hosted gateway, **Otari.ai** (built on top of `any-llm`).
  ```python
  from any_llm import completion
  response = completion(model="mistral-small-latest", provider="mistral", messages=[{"role":"user","content":"Hello!"}])
  ```
- **any-guardrail** (Python, `pip install any-guardrail`) — common interface across safety/guardrail models (Llama Guard, ShieldGemma, Deepset, Selene) for toxicity/jailbreak/PII checks.
  ```python
  from any_guardrail import AnyGuardrail, GuardrailName
  guardrail = AnyGuardrail.create(GuardrailName.DEEPSET)
  result = guardrail.validate("How do I hack into a system?")
  ```
- **mcpd** — **confirmed written in Go** (verified via `go.mod`/Makefile/build requirements), a daemon that declaratively manages and runs multiple MCP servers as STDIO subprocesses, exposing them over clean HTTP endpoints with lifecycle management and secret injection. Install via `brew tap mozilla-ai/tap && brew install mcpd`, or the `mzdotai/mcpd` Docker image.
  ```bash
  mcpd init
  mcpd add time
  mcpd daemon --dev --log-level=DEBUG
  # call: POST http://localhost:8090/api/v1/servers/time/tools/<tool>
  ```
- **Lumigator** (Python/FastAPI) — open-source app for comparing/choosing the best LLM for a task with task-specific metrics + GEval LLM-as-judge; more of a pre-hackathon model-selection tool than a live pipeline component.
- **Blueprints** (`blueprints.mozilla.ai`) — curated, ready-to-use AI app recipes. Directly relevant: **speech-to-text** and **speech-to-text-alignment** Blueprints, built on "Speaches," a self-hosted, OpenAI-Whisper-API-compatible server — a near-direct match for the audio-capture leg of a meeting assistant.

### The Rust investigation — findings
**High confidence answer: `encoderfile`.** A current, actively developed Mozilla.ai project **written in Rust** (using ONNX Runtime for inference, with Python bindings), explicitly positioned as llamafile's sibling: it packages transformer **encoder** models (embeddings, classification, NER) into a single self-contained binary — "no Python runtime, no dependencies, no network calls." Blog posts: "Encoderfile v0.1.0" (Nov 2025) and "Encoderfile's New Format" (Apr 2026); published on crates.io. This matches the recollection well: llamafile itself is C/C++ (llama.cpp + Cosmopolitan libc), and Mozilla.ai has now built a **Rust-native, AI-focused successor/sibling in the same single-file, low-level, no-dependency spirit**. ([github.com/mozilla-ai/encoderfile](https://github.com/mozilla-ai/encoderfile), [blog.mozilla.ai — Encoderfile v0.1.0](https://blog.mozilla.ai/encoderfile-v0-1-0-deploy-encoder-transformers-as-single-binary-executables/))

**Lower-confidence secondary candidate**: Wasmtime/Cranelift (Rust WASM runtime + code generator, originally built at Mozilla, now under the Bytecode Alliance) plus the **wasi-nn** WASI proposal for ML inference inside WebAssembly. This is governed by the Bytecode Alliance today, not branded "Mozilla.ai," so it's a weaker match. **Ruled out**: Mozilla.ai's "wasm-agents" Blueprint runs on Python via Pyodide, not Rust; no evidence found of a full Rust rewrite of llamafile itself (which remains C/C++).

### License / cost
All six core libraries are **Apache-2.0**, free, self-hostable. Paid layers exist only on top: **Otari.ai** (hosted LLM gateway built on `any-llm` — routing/budgets/observability as a paid product) and **Octonous** (beta commercial agent-automation platform, pricing undisclosed) — notably, Octonous is explicitly framed around "approval requirements before actions, transparent logs, permission scoping," i.e., the same human-approval-gated pattern our project needs, worth citing as external validation of the pattern.

### Fit for meeting assistant
- **`any-agent`/`tinyagent`** powers the "listens and proactively suggests actions" agent; swap frameworks without rewrites, get free OpenTelemetry traces for a demo-friendly execution log.
- **`any-llm`** backs the suggestion-generation LLM calls with one call signature; flip providers (OpenAI ↔ local Ollama) live if needed.
- **`any-guardrail`** validates/sanitizes every proposed action before it's shown to the user or handed to a background job — a direct fit for the human-approval gate.
- **`mcpd`** runs/manages the MCP servers the agent calls as tools (calendar, email, task tracker) declaratively, with secrets handled outside app code.
- **Blueprints (speech-to-text)** jumpstart the audio-transcription leg via the Whisper/Speaches Blueprint instead of building STT from scratch.
- **`encoderfile`** (optional/stretch) — compile a small "is this utterance actionable?" classifier into a dependency-free binary for fast local pre-filtering before invoking the LLM.

### What would impress them
Mozilla.ai is listed as a "Developer Infrastructure Partner" for this hackathon (no dedicated prize category found, and their sponsor page notes starter materials are still being finalized). Their own site names the **"Choice-first Stack"** (`any-agent` + `any-llm` + `any-guardrail` + `mcpd` together) as the current flagship bundle to showcase — using all four together, not just one, would be the strongest match to what they're promoting.

### Could not verify
- Any Mozilla.ai-specific hackathon starter kit or prize details for this event.
- The Rust investigation is a best-evidence reconciliation, not a confirmed match to what the user specifically recalled — `encoderfile` is high confidence given it directly fits "low-level Rust, now AI-focused," but present it as inference, not certainty.

**Key docs:** [github.com/mozilla-ai/any-agent](https://github.com/mozilla-ai/any-agent) · [github.com/mozilla-ai/tinyagent](https://github.com/mozilla-ai/tinyagent) · [github.com/mozilla-ai/any-llm](https://github.com/mozilla-ai/any-llm) · [github.com/mozilla-ai/any-guardrail](https://github.com/mozilla-ai/any-guardrail) · [github.com/mozilla-ai/mcpd](https://github.com/mozilla-ai/mcpd) · [blueprints.mozilla.ai](https://blueprints.mozilla.ai/) · [github.com/mozilla-ai/encoderfile](https://github.com/mozilla-ai/encoderfile) · [mozilla.ai/open-tools/choice-first-stack](https://www.mozilla.ai/open-tools/choice-first-stack)

---

## 8. Ambiguous AI

### What it is / current flagship offerings
**Ambiguous** ("the workspace built for human-AI collaboration") is a from-scratch productivity suite of **17 apps** — Docs, Sheets, Slides, Wiki, Mail, Chat, Forms, Sign, Tasks, Calendar, CRM, Drive, Identity, Assistant, Admin, Automations, Platform — where humans and **AI coworkers** use identical interfaces, data formats, and APIs. Every app is "MCP-ready." ([ambiguous.ai](https://www.ambiguous.ai/), [ambiguous.ai/applications](https://www.ambiguous.ai/applications))

An **AI coworker** is not a chatbot sidebar — it gets a real workspace account: a company email (`name@workspace.ambiguous.ai`), calendar, drive, and API key, indistinguishable in the UI from a human teammate. It can be emailed, CC'd, @-mentioned in Chat, or assigned a Task, and "picks up work when it appears" until done. The founders frame this as an architectural bet — the workspace is redesigned around AI as a first-class participant rather than AI bolted onto legacy tools (an "factories rebuilt around electricity" analogy). ([Why AI coworkers deserve a workspace](https://www.ambiguous.ai/resources/blog/why-ai-coworkers-deserve-a-workspace)) Company founded 2025 (Bellevue, WA), backed by **a16z Speedrun** (cohort 005). ([speedrun.a16z.com/companies/ambiguous](https://speedrun.a16z.com/companies/ambiguous))

### CLI, MCP server, and integration — concrete details
**CLI**: official npm package **`ambiguous`** (`npm install -g ambiguous` or `npx ambiguous ...`, no install needed). Provisioning a new coworker identity takes seconds:
```bash
npx ambiguous auth signup --name "My Agent" --human-email you@example.com
# → Workspace provisioned in 4.2s
# → API key written to ./.ambi/config.json
# → Email: my-agent@<workspace>.ambiguous.ai
# → MCP endpoint: https://app.ambiguous.ai/mcp

npx ambiguous docs create --type doc --title "Q4 Revenue Plan" --content "..."
npx ambiguous mail send --to team@company.com --subject "Weekly update" --body-markdown "..."
npx ambiguous tasks update <taskId> --status done
```
This confirms the "**get started in under a minute**" claim — the CLI/MCP setup genuinely completes in seconds. ([ambiguous.ai/agents/cli](https://www.ambiguous.ai/agents/cli), [npmjs.com/package/ambiguous](https://www.npmjs.com/package/ambiguous))

**MCP server**: `https://app.ambiguous.ai/mcp`, HTTP transport, Bearer-token auth:
```json
{ "mcpServers": { "ambiguous": {
  "type": "http", "url": "https://app.ambiguous.ai/mcp",
  "headers": { "Authorization": "Bearer <your-api-key>" }
}}}
```
Works with Claude Desktop/Cursor (paste into settings), ChatGPT (Connected Apps), or any MCP-compatible agent host. A **shared demo workspace key that resets weekly** is offered for instant testing. ([ambiguous.ai/agents/mcp](https://www.ambiguous.ai/agents/mcp))

Confirmed MCP tool names — one dotted namespace per app, exactly the actions our meeting assistant needs:
```js
await mcp.callTool("docs.create", { title, content: [...] });
await mcp.callTool("tasks.create", { title, assignee: "research-bot@acme.ambiguous.ai", priority: "high" });
await mcp.callTool("tasks.update", { task_id: "TASK-142", status: "completed", output_url: "..." });
await mcp.callTool("calendar.checkAvailability", { users: [...], range: { start, end } });
await mcp.callTool("calendar.createEvent", { title, start, end, attendees: [...] });
await mcp.callTool("mail.send", { to: [...], subject, body });
await mcp.callTool("chat.sendMessage", { channel: "general", text });
```
A parallel REST API (OpenAPI 3.1, Scalar-hosted) mirrors every MCP tool at `https://app.ambiguous.ai/api/{module}`. ([ambiguous.ai/agents/api](https://www.ambiguous.ai/agents/api))

**Registering our agent as an AI coworker identity** — this is the key mechanic for us, via Ambiguous's official "recipes": ([ambiguous.ai/agents/recipes](https://www.ambiguous.ai/agents/recipes))
```ts
const provisioned = await post("/api/admin/agents/provision", ADMIN_KEY, { display_name: "Research Bot" });
const agentKey = provisioned.api_key; // ak_... — this IS the coworker's identity, shown once
```
Optionally register a webhook (`task.assigned`, `email.received`, `document.shared`, HMAC-signed) so the coworker reacts to workspace events — enabling a human-to-agent loop: a human assigns a Task → webhook fires → coworker does the work → posts a comment with output links → PATCHes status to `done`.

**Note**: no confirmed way to attach a coworker directly to a live meeting/audio product was found — the "coworker" concept is workspace-app-native (Gmail/Docs/Slack-style), not a meeting-transcription integration. **Not found**: any native meeting-audio or calendar-invite-listening feature of Ambiguous itself. Our desktop app remains responsible for capture/transcription/suggestion; Ambiguous is purely the execution/attribution target.

### Free tier
**Free**: up to **5 teammates**, all 17 apps, **1,000 pooled AI actions/month**, MCP + CLI + REST + webhooks + audit logs all included (confirms the "free tier for teams up to 5" recollection). **Pro**: $20/seat/month, 5,000 actions/seat. Non-expiring action top-ups available ($5→500, $20→2,500, $50→10,000). ([ambiguous.ai/pricing](https://www.ambiguous.ai/pricing))

### Fit for meeting assistant
Ambiguous is the natural **execution + attribution layer** for approved suggestions — once a human approves a suggested action, a background job (e.g., a Trigger.dev task) calls the Ambiguous MCP/REST API under our meeting-assistant's own provisioned coworker identity, so every action is visibly attributed to a real "teammate" (e.g. `meeting-assistant@ws-xxxx.ambiguous.ai`) in the workspace roster, audit log, and apps:
- "Create a task" → `tasks.create`
- "Draft an email" → `mail.send`
- "Schedule a follow-up" → `calendar.checkAvailability` + `calendar.createEvent`
- "Look this up" → write the researched answer into `docs.create` or post via `chat.sendMessage`

This gives the demo a concrete, visually verifiable payoff: judges can open the live Ambiguous workspace and see the meeting assistant's coworker account actually creating the task/email/event/doc in real time, not just logging an API call.

### What would impress them
There is a confirmed **"Best Use of Ambiguous AI" prize (NVIDIA DGX Spark)** at this event. Ambiguous's sponsor listing description explicitly highlights "17 productivity apps rebuilt from scratch... agent integration through CLI or MCP **in under a minute**" — so provisioning the coworker identity live during the demo (`npx ambiguous auth signup`, ~4 seconds) and then visibly having it complete real work across multiple apps (not just one) is likely the strongest way to match their pitch. With blog/changelog content still thin, the **recipes page** (human-assigns-task → coworker-completes-it loop) is the clearest first-party signal of the exact UX pattern they want to see showcased.

### Could not verify
- No dedicated Ambiguous hackathon page, starter repo, or judging rubric was found (only the prize + short blurb on the AI Tinkerers event page).
- No dedicated `docs.ambiguous.ai` subdomain exists; docs live under `ambiguous.ai/agents/*`.
- Claims of a Google/Gemini Enterprise partnership surfaced in search summaries but could not be confirmed on any Ambiguous or Google page fetched directly.
- An older a16z Speedrun profile describes a different, earlier product framing ("agentic operating system" with named agents like @oliver/@claire) — treat as historical/superseded, not current messaging.
- Whether the CLI is open source — no public source repo was found (the `ambiguous-ai` GitHub org has only `.github` and `plugins` repos), suggesting it's closed-source/npm-distributed only.

**Key docs:** [ambiguous.ai/agents](https://www.ambiguous.ai/agents) · [ambiguous.ai/agents/mcp](https://www.ambiguous.ai/agents/mcp) · [ambiguous.ai/agents/cli](https://www.ambiguous.ai/agents/cli) · [ambiguous.ai/agents/api](https://www.ambiguous.ai/agents/api) · [ambiguous.ai/agents/recipes](https://www.ambiguous.ai/agents/recipes) · [ambiguous.ai/pricing](https://www.ambiguous.ai/pricing) · [npmjs.com/package/ambiguous](https://www.npmjs.com/package/ambiguous)

---

## 9. Cross-Sponsor Recommended Architecture

| Pipeline stage | Owner | Why |
|---|---|---|
| Audio capture → live transcription | **OpenAI Realtime API** (`gpt-live-transcribe`), optionally backed by **Mozilla.ai's speech-to-text Blueprint** (Whisper/Speaches) as a local fallback | Purpose-built live transcription models; Blueprint gives a self-hosted fallback for demo resilience |
| Suggestion-generation agent (the "brain" that watches the transcript and proposes actions) | **OpenAI Agents SDK** (Responses API) as the primary framework, routed through **OpenRouter** for provider fallback/model flexibility, with **Mozilla.ai `any-agent`/`any-llm`** as an optional abstraction layer if framework-swapping matters for the demo narrative | Agents SDK gives native `needsApproval` tool semantics; OpenRouter adds resilience + the `:online` search plugin; any-llm/any-agent make the choice-of-model/framework a selling point |
| Guardrails on proposed actions | **Mozilla.ai `any-guardrail`** | Validates/sanitizes a suggestion (e.g., drafted email text) before it's ever shown to the user |
| "Look this up" research action | **Exa** (Answer / Research API, or MCP server) | Purpose-built cited web research, directly pluggable as a tool |
| Frontend: live transcript view, generative UI suggestion cards, approve/reject UX | **CopilotKit** (CoAgents shared state + `useCopilotAction`/`renderAndWaitForResponse`) | This is exactly the "shared state + generative UI + HITL" story CopilotKit's judges want to see |
| Background job execution once approved | **Trigger.dev** (`task()`, `wait.forToken` for the approval pause, `triggerAndWait` for chaining, `delay` for scheduled follow-ups, Realtime for live status) | Purpose-built durable execution + human-in-the-loop waitpoints + live status streaming |
| Identity, and getting real access tokens to act on the user's behalf (Calendar/Gmail/Slack/GitHub) | **Auth0** (Universal Login + Token Vault) | Removes all custom OAuth plumbing; tokens are scoped and auto-refreshed |
| The actual "are you sure?" human approval gate for sensitive actions (send email, book calendar event) | **Auth0 CIBA** (async authorization, phone push) layered *inside* the Trigger.dev task, in addition to (or instead of) a plain in-app CopilotKit approval card | Gives a real, out-of-band, cryptographically-backed approval — more impressive and more robust than a UI button alone, and survives the desktop app being closed |
| MCP server management for whichever external tools are exposed as MCP | **Mozilla.ai `mcpd`** | Declarative, secret-safe management of multiple MCP servers (calendar, email, task tracker) as one daemon |
| Actual execution target + attribution for approved actions | **Ambiguous AI** — the meeting assistant provisions itself as an AI coworker (`npx ambiguous auth signup`) and calls its MCP server (`tasks.create`, `mail.send`, `calendar.createEvent`, `docs.create`, `chat.sendMessage`) from inside the Trigger.dev task, once approved | Gives judges a visually verifiable payoff: the approved suggestion becomes a real, attributed item in a live Ambiguous workspace, not just an API log line |

**Suggested narrative for judges**: "**Listen** (OpenAI Realtime `gpt-live-transcribe`, optionally backed by Mozilla.ai's speech-to-text Blueprint) → **Think** (OpenAI Agents SDK / Responses API, routed through OpenRouter for resilience, guarded by Mozilla.ai `any-guardrail`) → **Show** (CopilotKit CoAgents shared state + generative UI suggestion cards) → **Approve** (CopilotKit `renderAndWaitForResponse` in-app card, and/or Auth0 CIBA phone push for the most sensitive actions like sending an email) → **Do** (Trigger.dev background task, paused on `wait.forToken` until approval, authenticated via Auth0 Token Vault for Calendar/Gmail/Slack, optionally enriched via Exa's Answer/Research API for "look this up," and executed as a real, attributed action inside Ambiguous AI's workspace under our agent's own AI-coworker identity)."

This uses every sponsor for a distinct, non-overlapping piece of the pipeline rather than superficially bolting on SDKs, and it gives judges from *every* sponsor a concrete, demoable moment that showcases their newest 2026 feature (OpenAI's native MCP/approval primitives, CopilotKit's AG-UI + generative UI, OpenRouter's Agent SDK/Shell tool, Exa Agent, Trigger.dev waitpoints, Auth0 CIBA + Token Vault, Mozilla.ai's Choice-first Stack, and Ambiguous's under-a-minute AI-coworker provisioning).
