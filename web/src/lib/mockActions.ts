// Demo fixture for the Actions UI. Reached only via the `?mock=actions` URL
// flag on the session page — nothing imports it on the production path, so a
// real session never sees these. Lets the tab be demoed and screenshotted with
// no engine running.
import type { Action } from "@/types/action"
import type { SessionDetail } from "./engine"

export const MOCK_ACTIONS: Action[] = [
  {
    id: "a7f3",
    kind: "create_task",
    title: "Send Ana the Q3 architecture diagram",
    rationale: "Ana asked for it and you said you'd send it today.",
    evidence: [
      "Ana: Could you send me the Q3 architecture diagram before standup?",
      "You: Yeah, I'll get that over to you today.",
    ],
    confidence: 0.82,
    tool: "ambiguous.tasks.create",
    args: {
      title: "Send Ana the Q3 architecture diagram",
      assignee: "me",
      due: "2026-09-15",
      notes: "Latest export lives in the platform drive.",
    },
    status: "suggested",
  },
  {
    id: "b2c9",
    kind: "schedule_followup",
    title: "Book 30 min with Marcus on the migration cutover",
    rationale:
      "The cutover window was left open and Marcus asked to take it offline.",
    evidence: [
      "Marcus: We should take the cutover date offline, this isn't the room for it.",
    ],
    confidence: 0.64,
    tool: "ambiguous.calendar.createEvent",
    args: {
      title: "Migration cutover window",
      when: "2026-09-16T15:00:00Z",
      attendees: ["marcus@example.com"],
      notes: "Pick the cutover date, agree the rollback trigger.",
    },
    status: "suggested",
  },
  {
    id: "c5d1",
    kind: "draft_message",
    title: "Reply to Priya with the revised pricing table",
    rationale:
      "Priya is blocked on the numbers and expects them before the client call.",
    evidence: [
      "Priya: I can't send the deck until I have the revised pricing table.",
    ],
    confidence: 0.91,
    tool: "ambiguous.chat.sendMessage",
    args: {
      to: "priya@example.com",
      body: "Hi Priya — attaching the revised pricing table from today's call. The enterprise tier moved to annual-only; everything else is unchanged.",
    },
    status: "suggested",
  },
  {
    id: "d8e4",
    kind: "create_doc",
    title: "Write up the decision log for the storage rewrite",
    rationale: "Three decisions were made with no owner recording them.",
    evidence: [
      "You: Let's capture these decisions somewhere before we forget the reasoning.",
    ],
    confidence: 0.73,
    tool: "ambiguous.docs.create",
    args: {
      title: "Storage rewrite — decision log",
      body: "Context\nDecisions\nRejected alternatives\nOpen questions",
    },
    status: "succeeded",
    approvedBy: "auth0|demo-user",
    runId: "run_7f21ab",
    resultUrl: "https://example.com/docs/storage-rewrite-decision-log",
  },
]

/** A believable ended session so the page renders end-to-end without the
 * engine. Only the fields the session view reads are populated. */
export function mockSessionDetail(id: string): SessionDetail {
  return {
    id,
    title: "Platform sync (demo)",
    blurb: "Mocked session for the actions demo.",
    tags: ["demo"],
    startedAt: "2026-09-12T15:00:00Z",
    durationSec: 1860,
    speakers: [
      { id: 0, label: "Ana" },
      { id: 1, label: "Marcus" },
    ],
    questionCount: 2,
    backend: "mock",
    status: "ended",
    finals: 3,
    transcript: [
      {
        tStart: 12,
        text: "Could you send me the Q3 architecture diagram before standup?",
        speakerId: 0,
        speaker: "Ana",
        source: "system",
      },
      {
        tStart: 18,
        text: "Yeah, I'll get that over to you today.",
        speakerId: null,
        speaker: "You",
        source: "mic",
      },
      {
        tStart: 240,
        text: "We should take the cutover date offline, this isn't the room for it.",
        speakerId: 1,
        speaker: "Marcus",
        source: "system",
      },
    ],
    summary: {
      text: "Mocked session used to demo suggested actions.",
      updatedAt: null,
      forcedFinal: true,
    },
    archive: null,
    qa: [],
    questionsForMe: [],
    actions: MOCK_ACTIONS,
    speakerLabels: { "0": "Ana", "1": "Marcus" },
    selfName: "You",
    context: "Demo mode — no engine attached.",
  }
}
