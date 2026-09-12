export interface Speaker {
  id: number
  label: string | null
  locked?: boolean
}

export interface TranscriptLine {
  tStart: number
  text: string
  speakerId: number | null
  source: "system" | "mic"
}

export interface QuestionAnswer {
  id: string
  question: string
  answer?: string
  askedAt: number | null
  speakerId?: number | null
}

export interface SessionSummary {
  text: string
  updatedAt: string
  forcedFinal?: boolean
}

export interface Session {
  id: string
  title: string
  startedAt: string
  durationSec: number
  speakers: Speaker[]
  questionCount: number
  summary: SessionSummary
  transcript?: TranscriptLine[]
  qa?: QuestionAnswer[]
}
