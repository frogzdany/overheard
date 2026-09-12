"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import {
  Alert,
  Box,
  Button,
  Flex,
  Heading,
  Input,
  InputGroup,
  SimpleGrid,
  Spinner,
  Text,
} from "@chakra-ui/react"
import { useRouter } from "next/navigation"
import { LuPlus, LuSearch } from "react-icons/lu"
import { SessionCard } from "@/components/sessions/SessionCard"
import { NewSessionDialog } from "@/components/sessions/NewSessionDialog"
import { ConfirmDialog } from "@/components/ConfirmDialog"
import {
  engineApi,
  summaryToCardSession,
  type SessionSummary,
} from "@/lib/engine"

// The engine can take a moment to come up; give it headroom before declaring
// it unreachable.
const COLD_START_GRACE_MS = 25_000

export default function Page() {
  const router = useRouter()
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null)
  const [engineState, setEngineState] = useState<
    "starting" | "ready" | "unreachable"
  >("starting")
  const [running, setRunning] = useState<string | null>(null)
  const [newOpen, setNewOpen] = useState(false)
  const [search, setSearch] = useState("")
  const [pendingDelete, setPendingDelete] = useState<SessionSummary | null>(null)
  const mountedAt = useRef<number>(0)

  useEffect(() => {
    mountedAt.current = Date.now()
    let cancelled = false
    const load = async () => {
      try {
        const [list, health] = await Promise.all([
          engineApi.listSessions(),
          engineApi.health(),
        ])
        if (cancelled) return
        setSessions(list)
        setRunning(health.currentSessionId)
        setEngineState("ready")
      } catch {
        if (cancelled) return
        const elapsed = Date.now() - mountedAt.current
        setEngineState(elapsed < COLD_START_GRACE_MS ? "starting" : "unreachable")
      }
    }
    load()
    const tick = () => load()
    let interval = setInterval(tick, 1_000)
    const watch = setInterval(() => {
      if (engineState === "ready") {
        clearInterval(interval)
        interval = setInterval(tick, 5_000)
        clearInterval(watch)
      }
    }, 500)
    return () => {
      cancelled = true
      clearInterval(interval)
      clearInterval(watch)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const onStarted = (id: string) => {
    setNewOpen(false)
    router.push(`/session?id=${encodeURIComponent(id)}`)
  }

  const filtered = useMemo(() => {
    if (!sessions) return null
    const needle = search.trim().toLowerCase()
    return sessions.filter((s) => {
      if (!needle) return true
      const hay = [
        s.title,
        s.blurb ?? "",
        (s.tags ?? []).join(" "),
        s.id,
      ].join(" ").toLowerCase()
      return hay.includes(needle)
    })
  }, [sessions, search])

  const newSessionDisabled = !!running || engineState !== "ready"

  return (
    <Box>
      <Flex align="center" justify="space-between" mb="4" gap="4" wrap="wrap">
        <Box>
          <Heading size="xl">Your sessions</Heading>
          <Text color="fg.muted" mt="1">
            {engineState === "starting" && sessions === null
              ? "Starting engine…"
              : sessions
                ? `${filtered?.length ?? 0} of ${sessions.length} shown`
                : "Loading…"}
            {running ? " · live session in progress" : ""}
          </Text>
        </Box>
        <Flex gap="2">
          {running ? (
            <Button
              colorPalette="red"
              variant="surface"
              onClick={() => router.push(`/session?id=${encodeURIComponent(running)}`)}
            >
              Open live session
            </Button>
          ) : null}
          <Button
            colorPalette="blue"
            onClick={() => setNewOpen(true)}
            disabled={newSessionDisabled}
          >
            <LuPlus /> New session
          </Button>
        </Flex>
      </Flex>

      {engineState === "unreachable" ? (
        <Alert.Root status="error" mb="6">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>Engine not reachable</Alert.Title>
            <Alert.Description>
              The local audio engine isn&apos;t responding on
              {" "}<code>127.0.0.1:8765</code>. Start it with{" "}
              <code>./run-dev.sh</code> (or{" "}
              <code>python app.py --no-window --port=8765</code>) and check its
              log for errors.
            </Alert.Description>
          </Alert.Content>
        </Alert.Root>
      ) : null}

      {engineState === "starting" && sessions === null ? (
        <Flex
          borderWidth="1px"
          borderColor="border"
          rounded="lg"
          p="10"
          minH="40"
          direction="column"
          align="center"
          justify="center"
          gap="3"
          color="fg.muted"
        >
          <Spinner />
          <Text fontSize="sm" textAlign="center">
            Starting the local engine — this can take a few seconds on first
            launch.
          </Text>
        </Flex>
      ) : null}

      {sessions && sessions.length > 0 ? (
        <Flex direction="column" gap="3" mb="4">
          <InputGroup startElement={<LuSearch />} maxW="md">
            <Input
              placeholder="Search title, blurb, tags…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </InputGroup>
        </Flex>
      ) : null}

      {engineState === "ready" && sessions && sessions.length === 0 ? (
        <Box
          borderWidth="1px"
          borderColor="border"
          rounded="lg"
          p="10"
          textAlign="center"
          color="fg.muted"
        >
          <Text>No sessions yet. Click <b>New session</b> to start one.</Text>
        </Box>
      ) : null}

      {filtered && filtered.length === 0 && sessions && sessions.length > 0 ? (
        <Box
          borderWidth="1px"
          borderColor="border"
          rounded="lg"
          p="10"
          textAlign="center"
          color="fg.muted"
        >
          <Text>No sessions match the current search.</Text>
        </Box>
      ) : null}

      {filtered && filtered.length > 0 ? (
        <SimpleGrid columns={{ base: 1, md: 2, xl: 3 }} gap="4">
          {filtered.map((s) => (
            <SessionCard
              key={s.id}
              session={summaryToCardSession(s)}
              extra={s}
              onDelete={s.id === running ? undefined : () => setPendingDelete(s)}
            />
          ))}
        </SimpleGrid>
      ) : null}

      <NewSessionDialog
        open={newOpen}
        onClose={() => setNewOpen(false)}
        onStarted={onStarted}
      />

      <ConfirmDialog
        open={pendingDelete !== null}
        title={`Delete "${pendingDelete?.title ?? ""}"?`}
        destructive
        confirmLabel="Delete session"
        body={
          <Text>
            This will permanently remove the session and its transcript,
            summary, and audio files. This cannot be undone.
          </Text>
        }
        onClose={() => setPendingDelete(null)}
        onConfirm={async () => {
          if (!pendingDelete) return
          await engineApi.deleteSession(pendingDelete.id)
          setSessions((prev) =>
            prev ? prev.filter((x) => x.id !== pendingDelete.id) : prev,
          )
        }}
      />
    </Box>
  )
}
