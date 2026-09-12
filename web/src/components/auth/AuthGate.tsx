"use client"

// Sign-in gate for the browser dashboard when Auth0 is configured. Runs the
// redirect-callback handling + token caching, and blocks the app behind a
// Sign-in button until authenticated. When Auth0 isn't configured (no
// NEXT_PUBLIC_AUTH0_DOMAIN) the gate is a pass-through, so the dashboard runs
// locally without any tenant values.

import { useEffect, useState } from "react"
import { Button, Flex, Heading, Text } from "@chakra-ui/react"
import { auth0Configured, initAuth, signIn } from "@/lib/auth"

export function AuthGate({ children }: { children: React.ReactNode }) {
  const configured = auth0Configured()
  const [state, setState] = useState<"loading" | "in" | "out">("loading")

  useEffect(() => {
    if (!configured) return
    let cancelled = false
    initAuth()
      .then((ok) => {
        if (!cancelled) setState(ok ? "in" : "out")
      })
      .catch(() => {
        if (!cancelled) setState("out")
      })
    return () => {
      cancelled = true
    }
  }, [configured])

  if (!configured) return <>{children}</>
  if (state === "in") return <>{children}</>

  return (
    <Flex minH="100vh" align="center" justify="center" direction="column" gap="4" bg="bg" p="6">
      <Heading size="lg">Overheard</Heading>
      {state === "loading" ? (
        <Text color="fg.muted">Checking sign-in…</Text>
      ) : (
        <>
          <Text color="fg.muted">Sign in to connect to your meetings.</Text>
          <Button colorPalette="blue" onClick={() => void signIn()}>
            Sign in
          </Button>
        </>
      )}
    </Flex>
  )
}
