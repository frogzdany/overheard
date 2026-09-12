// Centralized UTC date/time formatting.
//
// Engine timestamps arrive in two shapes: ISO-8601 strings (e.g. session
// `startedAt`) and unix SECONDS (e.g. summary `updatedAt`). Everything is
// rendered in UTC so a recording reads the same on every machine, and invalid
// / missing values render as an em dash instead of "Invalid Date".

const LOCALE = "en-US"
const UTC = "UTC"
const INVALID = "—"

function toDate(value: string | number | Date): Date {
  return value instanceof Date ? value : new Date(value)
}

function isValid(d: Date): boolean {
  return !Number.isNaN(d.getTime())
}

/** Medium date + short time in UTC, e.g. "Jun 5, 2026, 4:18 PM". */
export function formatDateTime(value: string | number | Date | null | undefined): string {
  if (value === null || value === undefined) return INVALID
  const d = toDate(value)
  if (!isValid(d)) return INVALID
  return d.toLocaleString(LOCALE, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: UTC,
  })
}

/** Time-of-day only, in UTC, e.g. "4:18:55 PM". */
export function formatTimeUTC(value: string | number | Date | null | undefined): string {
  if (value === null || value === undefined) return INVALID
  const d = toDate(value)
  if (!isValid(d)) return INVALID
  return d.toLocaleTimeString(LOCALE, { timeZone: UTC })
}

/** Time-of-day from a unix-SECONDS timestamp (engine convention), in UTC. */
export function formatUnixSecondsTime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return INVALID
  return formatTimeUTC(seconds * 1000)
}

/** Time-of-day from either engine timestamp shape: unix SECONDS (live bus
 * events) or an ISO-8601 string (JSONL replays served over REST), in UTC. */
export function formatEngineTime(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return INVALID
  return typeof value === "number" ? formatTimeUTC(value * 1000) : formatTimeUTC(value)
}
