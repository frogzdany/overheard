"use client"

import { useState } from "react"
import {
  Alert,
  Button,
  Dialog,
  Portal,
  Stack,
  Text,
} from "@chakra-ui/react"

interface Props {
  open: boolean
  title: string
  body: React.ReactNode
  confirmLabel?: string
  destructive?: boolean
  onClose: () => void
  /** Returns a promise; close happens after it resolves. Rejection shows
   * the error inside the dialog and keeps it open. */
  onConfirm: () => Promise<void> | void
}

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "Confirm",
  destructive = false,
  onClose,
  onConfirm,
}: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleConfirm = async () => {
    setBusy(true)
    setError(null)
    try {
      await onConfirm()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(d) => (!d.open && !busy ? onClose() : null)}
      placement="center"
      size="sm"
    >
      <Portal>
        <Dialog.Backdrop />
        <Dialog.Positioner>
          <Dialog.Content>
            <Dialog.Header>
              <Dialog.Title>{title}</Dialog.Title>
            </Dialog.Header>
            <Dialog.Body>
              <Stack gap="3">
                {typeof body === "string" ? <Text>{body}</Text> : body}
                {error ? (
                  <Alert.Root status="error">
                    <Alert.Indicator />
                    <Alert.Content>
                      <Alert.Description>{error}</Alert.Description>
                    </Alert.Content>
                  </Alert.Root>
                ) : null}
              </Stack>
            </Dialog.Body>
            <Dialog.Footer>
              <Button variant="ghost" onClick={onClose} disabled={busy}>
                Cancel
              </Button>
              <Button
                colorPalette={destructive ? "red" : "blue"}
                onClick={handleConfirm}
                loading={busy}
              >
                {confirmLabel}
              </Button>
            </Dialog.Footer>
          </Dialog.Content>
        </Dialog.Positioner>
      </Portal>
    </Dialog.Root>
  )
}
