"use client"

import { Alert, Button, Flex, Text } from "@chakra-ui/react"
import {
  engineApi,
  openExternal,
  permissionsSatisfied,
  SETTINGS_URL,
  type PermissionsSnapshot,
} from "@/lib/engine"

/**
 * Pre-session permission guidance. Only renders on macOS when Screen Recording
 * or Microphone is not granted. Screen Recording silently "resets" on every
 * ad-hoc app rebuild (TCC keys on the binary's code-hash), so we explain the
 * toggle-off/on quirk and link straight to the right Settings pane.
 */
export function PermissionsNotice({
  perms,
  onRefresh,
}: {
  perms: PermissionsSnapshot | null
  onRefresh: () => void
}) {
  if (!perms || perms.platform !== "darwin") return null

  // Same readiness rule as the first-run SetupGate (shared source of truth), so
  // the two never disagree about whether capture is allowed to run.
  if (permissionsSatisfied(perms)) return null

  const srOk = perms.screenRecording === "granted"
  const micOk =
    perms.microphone === "granted" || perms.microphone === "unknown"

  const requestSR = async () => {
    try {
      await engineApi.requestScreenRecording()
    } catch {
      // non-fatal — fall through to re-check
    }
    onRefresh()
  }

  return (
    <Alert.Root status="warning" mb="3">
      <Alert.Indicator />
      <Alert.Content>
        <Alert.Title>Permissions needed to capture audio</Alert.Title>
        <Alert.Description>
          {!srOk ? (
            <Text>
              <b>Screen Recording</b> is required to capture system audio (the
              other side of the call).
            </Text>
          ) : null}
          {!micOk ? (
            <Text>
              <b>Microphone</b> access is required to capture your voice.
            </Text>
          ) : null}
          <Text mt="1" fontSize="xs" color="fg.muted">
            Already listed but still asking? After a rebuild macOS needs you to
            toggle the app off and back on in that list.
          </Text>

          <Flex gap="2" mt="2" wrap="wrap">
            {!srOk ? (
              <>
                <Button size="xs" colorPalette="orange" onClick={requestSR}>
                  Request screen access
                </Button>
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() => openExternal(SETTINGS_URL.screenRecording)}
                >
                  Open Screen Recording settings
                </Button>
              </>
            ) : null}
            {!micOk ? (
              <Button
                size="xs"
                variant="outline"
                onClick={() => openExternal(SETTINGS_URL.microphone)}
              >
                Open Microphone settings
              </Button>
            ) : null}
            <Button size="xs" variant="ghost" onClick={onRefresh}>
              Re-check
            </Button>
          </Flex>
        </Alert.Description>
      </Alert.Content>
    </Alert.Root>
  )
}
