"use client"

import { Alert, Button, Stack, Text } from "@chakra-ui/react"
import {
  openExternal,
  SETTINGS_URL,
  type EngineNotice,
} from "@/lib/engine"

// Per-code remediation: a short hint and (optionally) a deep-link action.
function remediation(code: string | null): {
  hint?: string
  action?: { label: string; url: string }
} {
  switch (code) {
    case "screen_recording":
      return {
        hint: "Already listed? After a rebuild macOS needs you to toggle the app off and on again in that list.",
        action: {
          label: "Open Screen Recording settings",
          url: SETTINGS_URL.screenRecording,
        },
      }
    case "microphone":
      return {
        action: {
          label: "Open Microphone settings",
          url: SETTINGS_URL.microphone,
        },
      }
    case "rate_limit":
      return {
        hint: "Groq’s daily token limit was reached — speaker labels and insights resume after it resets.",
      }
    default:
      return {}
  }
}

export function SessionNotices({ notices }: { notices: EngineNotice[] }) {
  if (!notices.length) return null
  // Show the most recent few, newest first.
  const recent = notices.slice(-3).reverse()

  return (
    <Stack gap="2" mb="4">
      {recent.map((n, i) => {
        const { hint, action } = remediation(n.code)
        return (
          <Alert.Root
            key={`${n.ts}-${i}`}
            status={n.level === "error" ? "error" : "warning"}
          >
            <Alert.Indicator />
            <Alert.Content>
              <Alert.Description>
                <Text>{n.message}</Text>
                {hint ? (
                  <Text mt="1" fontSize="xs" color="fg.muted">
                    {hint}
                  </Text>
                ) : null}
                {action ? (
                  <Button
                    size="xs"
                    mt="2"
                    variant="outline"
                    onClick={() => openExternal(action.url)}
                  >
                    {action.label}
                  </Button>
                ) : null}
              </Alert.Description>
            </Alert.Content>
          </Alert.Root>
        )
      })}
    </Stack>
  )
}
