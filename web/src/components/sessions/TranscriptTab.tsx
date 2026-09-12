"use client"

import { memo, useEffect, useRef, useState } from "react"
import { Badge, Box, Button, Flex, Stack, Switch, Text } from "@chakra-ui/react"
import { engineApi, fetchEngineBlob, type LiveTranscriptLine } from "@/lib/engine"

const AUTO_SCROLL_KEY = "ma:transcript:auto-scroll"
// Pixel slack: if the user is within this many px of the bottom we still
// consider them "at the bottom" and keep auto-scrolling.
const STICKY_THRESHOLD = 32
// How many recent finals stay mounted in the DOM. The full list lives in
// state (so the export stays complete) — only the visible
// window is capped to keep long meetings responsive.
const VISIBLE_LINES = 80

function resolveSpeaker(
  line: LiveTranscriptLine,
  labels: Record<string, string>,
  selfName: string,
): string {
  if (line.source === "mic") return selfName
  if (line.speakerId !== null && labels[String(line.speakerId)]) {
    return labels[String(line.speakerId)]
  }
  return line.speaker ?? "Speaker ?"
}

const SYSTEM_PALETTE = [
  "purple", "orange", "cyan", "pink", "teal", "yellow",
] as const

function badgePalette(line: LiveTranscriptLine): string {
  if (line.source === "mic") return "green"
  if (line.speakerId === null) return "gray"
  return SYSTEM_PALETTE[line.speakerId % SYSTEM_PALETTE.length]
}

interface RowProps {
  text: string
  speaker: string
  palette: string
}

// Memoized row — speaker label + text. Re-renders only when its own props
// change, so appending a new line at the bottom doesn't repaint older rows.
const TranscriptRow = memo(function TranscriptRow({
  text,
  speaker,
  palette,
}: RowProps) {
  return (
    <Flex gap="3" align="baseline">
      <Badge
        variant="subtle"
        colorPalette={palette}
        minW="20"
        flexShrink={0}
      >
        {speaker}
      </Badge>
      <Text whiteSpace="pre-wrap">{text}</Text>
    </Flex>
  )
})

export function TranscriptTab({
  sessionId,
  lines,
  interim,
  speakerLabels,
  selfName = "You",
}: {
  sessionId: string
  lines: LiveTranscriptLine[]
  interim: { system: string | null; mic: string | null }
  speakerLabels: Record<string, string>
  selfName?: string
}) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState<boolean>(true)
  const [showAll, setShowAll] = useState(false)
  const [downloading, setDownloading] = useState(false)

  // Pull the faithful transcript from the engine (built live from finals +
  // current labels) and save it.
  const download = async (fmt: "md" | "txt") => {
    setDownloading(true)
    try {
      const { blob } = await fetchEngineBlob(
        engineApi.transcriptDownloadPath(sessionId, fmt),
      )
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `${sessionId}.transcript.${fmt}`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      console.error(e)
    } finally {
      setDownloading(false)
    }
  }

  // Hydrate preference once on mount.
  useEffect(() => {
    if (typeof window === "undefined") return
    const stored = window.localStorage.getItem(AUTO_SCROLL_KEY)
    // Hydration-safe: the stored value can't be read during the server render,
    // so this one setState-in-effect is deliberate.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (stored !== null) setAutoScroll(stored === "1")
  }, [])

  useEffect(() => {
    if (typeof window === "undefined") return
    window.localStorage.setItem(AUTO_SCROLL_KEY, autoScroll ? "1" : "0")
  }, [autoScroll])

  useEffect(() => {
    if (!autoScroll) return
    const el = scrollRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [lines.length, interim.system, interim.mic, autoScroll])

  const ignoreScrollRef = useRef(false)
  useEffect(() => {
    if (!autoScroll) return
    ignoreScrollRef.current = true
    const id = requestAnimationFrame(() => {
      ignoreScrollRef.current = false
    })
    return () => cancelAnimationFrame(id)
  }, [lines.length, interim.system, interim.mic, autoScroll])

  const onScroll: React.UIEventHandler<HTMLDivElement> = (e) => {
    if (ignoreScrollRef.current) return
    const el = e.currentTarget
    const atBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight < STICKY_THRESHOLD
    if (!atBottom && autoScroll) {
      setAutoScroll(false)
    }
  }

  const hasContent =
    lines.length > 0 || interim.system !== null || interim.mic !== null

  if (!hasContent) {
    return (
      <Box py="10" textAlign="center" color="fg.muted">
        <Text>No transcript yet. Speak — it will appear here.</Text>
      </Box>
    )
  }

  const totalLines = lines.length
  const capped = !showAll && totalLines > VISIBLE_LINES
  const visibleLines = capped ? lines.slice(-VISIBLE_LINES) : lines
  // Stable index offset so memoized rows don't lose their key when the
  // window slides forward (line at absolute index N keeps key N).
  const indexOffset = totalLines - visibleLines.length

  return (
    <Box>
      <Flex align="center" justify="space-between" mb="2" gap="3" wrap="wrap">
        <Flex align="center" gap="3" wrap="wrap">
          <Text fontSize="xs" color="fg.muted">
            {capped
              ? `Showing last ${VISIBLE_LINES} of ${totalLines} lines`
              : `${totalLines} final line${totalLines === 1 ? "" : "s"}`}
          </Text>
          {totalLines > VISIBLE_LINES ? (
            <Button
              size="xs"
              variant="ghost"
              onClick={() => setShowAll((v) => !v)}
            >
              {showAll ? "Show recent only" : `Show all (${totalLines})`}
            </Button>
          ) : null}
        </Flex>
        <Flex align="center" gap="3" wrap="wrap">
          <Button
            size="xs"
            variant="outline"
            loading={downloading}
            disabled={totalLines === 0}
            onClick={() => download("md")}
            title="Download the faithful transcript with current speaker names"
          >
            Download .md
          </Button>
          <Button
            size="xs"
            variant="ghost"
            loading={downloading}
            disabled={totalLines === 0}
            onClick={() => download("txt")}
          >
            .txt
          </Button>
          <Switch.Root
            checked={autoScroll}
            onCheckedChange={(d) => setAutoScroll(d.checked)}
            size="sm"
          >
            <Switch.HiddenInput />
            <Switch.Control>
              <Switch.Thumb />
            </Switch.Control>
            <Switch.Label fontSize="xs" color="fg.muted">
              Auto-scroll
            </Switch.Label>
          </Switch.Root>
        </Flex>
      </Flex>

      <Box
        ref={scrollRef}
        onScroll={onScroll}
        maxH="65vh"
        overflowY="auto"
        px="1"
        py="4"
        borderWidth="1px"
        borderColor="border"
        rounded="md"
        bg="bg.subtle"
      >
        <Stack gap="3" px="3">
          {visibleLines.map((line, i) => (
            <TranscriptRow
              key={indexOffset + i}
              text={line.text}
              speaker={resolveSpeaker(line, speakerLabels, selfName)}
              palette={badgePalette(line)}
            />
          ))}

          {interim.mic ? (
            <Flex gap="3" align="baseline" opacity={0.6}>
              <Badge
                variant="outline"
                colorPalette="green"
                minW="20"
                flexShrink={0}
              >
                {selfName}
              </Badge>
              <Text whiteSpace="pre-wrap" fontStyle="italic">
                {interim.mic}
              </Text>
            </Flex>
          ) : null}

          {interim.system ? (
            <Flex gap="3" align="baseline" opacity={0.6}>
              <Badge
                variant="outline"
                colorPalette="purple"
                minW="20"
                flexShrink={0}
              >
                …
              </Badge>
              <Text whiteSpace="pre-wrap" fontStyle="italic">
                {interim.system}
              </Text>
            </Flex>
          ) : null}
        </Stack>
      </Box>
    </Box>
  )
}
