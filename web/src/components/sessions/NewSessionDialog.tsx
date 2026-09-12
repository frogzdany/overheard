"use client"

import { useEffect, useState } from "react"
import {
  Alert,
  Button,
  Dialog,
  Field,
  NativeSelect,
  Portal,
  Stack,
  Textarea,
} from "@chakra-ui/react"
import { LuPlay } from "react-icons/lu"
import {
  engineApi,
  type CaptureApp,
  type InputDevice,
  type NewSessionInitial,
  type PermissionsSnapshot,
  type Settings,
} from "@/lib/engine"
import { PermissionsNotice } from "@/components/sessions/PermissionsNotice"

const LANGUAGES: { value: string; label: string }[] = [
  { value: "", label: "Auto-detect" },
  { value: "en", label: "English" },
  { value: "es", label: "Spanish" },
  { value: "pt", label: "Portuguese" },
  { value: "fr", label: "French" },
  { value: "multi", label: "Multilingual (Deepgram)" },
]

interface NewSessionDialogProps {
  open: boolean
  onClose: () => void
  onStarted: (sessionId: string) => void
  /** Pre-fill from a launcher (e.g. "Continue" on an ended session). Applied
   * on top of the saved defaults; everything stays editable. */
  initial?: NewSessionInitial | null
}

export function NewSessionDialog({ open, onClose, onStarted, initial }: NewSessionDialogProps) {
  const [device, setDevice] = useState<string>("")
  const [language, setLanguage] = useState<string>("")
  const [context, setContext] = useState<string>("")
  const [devices, setDevices] = useState<InputDevice[]>([])
  const [settings, setSettings] = useState<Settings | null>(null)
  const [perms, setPerms] = useState<PermissionsSnapshot | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // App whose audio to capture. Empty = the whole system mix.
  const [apps, setApps] = useState<CaptureApp[]>([])
  const [captureApp, setCaptureApp] = useState<string>("")

  const refreshPerms = async () => {
    try {
      setPerms(await engineApi.getPermissions())
    } catch {
      // non-fatal: the preflight is advisory; the user can still start.
    }
  }

  // Load settings + devices when the dialog opens. We re-fetch each time so
  // saved defaults are picked up after the engine restarts.
  useEffect(() => {
    if (!open) return
    let cancelled = false
    const load = async () => {
      try {
        const [s, d, perm, appsRes] = await Promise.all([
          engineApi.getSettings(),
          engineApi.listDevices(),
          engineApi.getPermissions().catch(() => null),
          // Best-effort: missing helper / permission just hides the picker.
          engineApi.listApps().catch(() => ({ apps: [] as CaptureApp[] })),
        ])
        if (cancelled) return
        setSettings(s)
        setDevices(d.devices)
        setPerms(perm)
        setApps(appsRes.apps ?? [])
        setDevice(s.micDevice ?? "")
        setLanguage(s.defaultLanguage ?? "")
        setContext(s.defaultContext ?? "")
        // Launcher prefill (e.g. "Continue this meeting") goes on top of the
        // defaults. It must be applied here, after the loader — a separate
        // effect would race and get clobbered by the defaults.
        if (initial) {
          if (initial.context != null) setContext(initial.context)
          const hint = (initial.captureApp ?? "").trim()
          setCaptureApp(
            hint && (appsRes.apps ?? []).some((a) => a.bundleId === hint)
              ? hint
              : "",
          )
        } else {
          setCaptureApp("")
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [open, initial])

  const handleClose = () => {
    if (submitting) return
    setError(null)
    onClose()
  }

  const handleStart = async () => {
    setSubmitting(true)
    setError(null)
    try {
      const { id } = await engineApi.startSession({
        device: device || null,
        language: language || null,
        context: context.trim() || null,
        captureApps: captureApp ? [captureApp] : null,
      })
      onStarted(id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSubmitting(false)
    }
  }

  // Hide aggregate / virtual devices from the picker.
  const HIDDEN = new Set([
    "Meeting Input", "BlackHole 2ch", "ZoomAudioDevice", "Microsoft Teams Audio",
  ])
  const deviceOptions = devices.length
    ? devices.filter((d) => !HIDDEN.has(d.name))
    : settings
      ? [{ index: -1, name: settings.micDevice || "", channels: 0, sampleRate: 0 }]
      : []

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(d) => (!d.open ? handleClose() : null)}
      placement="center"
      size="md"
    >
      <Portal>
        <Dialog.Backdrop />
        <Dialog.Positioner>
          <Dialog.Content>
            <Dialog.Header>
              <Dialog.Title>Start a new session</Dialog.Title>
            </Dialog.Header>
            <Dialog.Body>
              <Stack gap="4">
                <PermissionsNotice perms={perms} onRefresh={refreshPerms} />

                {error ? (
                  <Alert.Root status="error">
                    <Alert.Indicator />
                    <Alert.Content>
                      <Alert.Title>Could not start</Alert.Title>
                      <Alert.Description>{error}</Alert.Description>
                    </Alert.Content>
                  </Alert.Root>
                ) : null}

                <Field.Root>
                  <Field.Label>Microphone</Field.Label>
                  <NativeSelect.Root>
                    <NativeSelect.Field
                      value={device}
                      onChange={(e) => setDevice(e.target.value)}
                    >
                      <option value="">— system default —</option>
                      {deviceOptions.map((d) => (
                        <option key={d.name || "default"} value={d.name}>
                          {d.name || "(unnamed)"}{d.channels ? ` (${d.channels} ch)` : ""}
                        </option>
                      ))}
                    </NativeSelect.Field>
                    <NativeSelect.Indicator />
                  </NativeSelect.Root>
                  <Field.HelperText>
                    System audio is always captured via ScreenCaptureKit; this
                    is just your physical mic for the &ldquo;You&rdquo; stream.
                  </Field.HelperText>
                </Field.Root>

                <Field.Root>
                  <Field.Label>Language</Field.Label>
                  <NativeSelect.Root>
                    <NativeSelect.Field
                      value={language}
                      onChange={(e) => setLanguage(e.target.value)}
                    >
                      {LANGUAGES.map((l) => (
                        <option key={l.value || "auto"} value={l.value}>
                          {l.label}
                        </option>
                      ))}
                    </NativeSelect.Field>
                    <NativeSelect.Indicator />
                  </NativeSelect.Root>
                </Field.Root>

                {apps.length ? (
                  <Field.Root>
                    <Field.Label>App to capture (optional)</Field.Label>
                    <NativeSelect.Root>
                      <NativeSelect.Field
                        value={captureApp}
                        onChange={(e) => setCaptureApp(e.target.value)}
                      >
                        <option value="">— whole system audio —</option>
                        {apps.map((a) => (
                          <option key={a.bundleId} value={a.bundleId}>
                            {a.name}
                          </option>
                        ))}
                      </NativeSelect.Field>
                      <NativeSelect.Indicator />
                    </NativeSelect.Root>
                    <Field.HelperText>
                      Pick your Zoom/Meet/Teams app to capture only its audio,
                      so notifications and music stay out of the transcript.
                    </Field.HelperText>
                  </Field.Root>
                ) : null}

                <Field.Root>
                  <Field.Label>Context (this session)</Field.Label>
                  <Textarea
                    value={context}
                    onChange={(e) => setContext(e.target.value)}
                    rows={4}
                    placeholder="Speakers, topics, project notes."
                  />
                  <Field.HelperText>
                    Starts pre-filled from your global default. Edits here are
                    used only for this session. Names and keywords here help the
                    transcript and the summary get the jargon right.
                  </Field.HelperText>
                </Field.Root>
              </Stack>
            </Dialog.Body>
            <Dialog.Footer>
              <Button variant="ghost" onClick={handleClose} disabled={submitting}>
                Cancel
              </Button>
              <Button
                colorPalette="blue"
                onClick={handleStart}
                loading={submitting}
              >
                <LuPlay /> Start
              </Button>
            </Dialog.Footer>
          </Dialog.Content>
        </Dialog.Positioner>
      </Portal>
    </Dialog.Root>
  )
}
