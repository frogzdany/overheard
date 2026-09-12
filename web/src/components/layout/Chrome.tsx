"use client"

import { CopilotKit } from "@copilotkit/react-core"
import { AppShell } from "./AppShell"
import { AuthGate } from "@/components/auth/AuthGate"

// CopilotKit's single-endpoint resource proxy parses runtimeUrl with a bare
// `new URL(runtimeUrl)` (no base), so a root-relative "/api/copilotkit" throws
// "Failed to construct 'URL': Invalid URL" and every agent connect fails. Give
// it an absolute URL in the browser; SSR keeps the relative form, which is
// never parsed on that path.
const RUNTIME_PATH = "/api/copilotkit"
function runtimeUrl(): string {
  if (typeof window === "undefined") return RUNTIME_PATH
  return `${window.location.origin}${RUNTIME_PATH}`
}

export function Chrome({ children }: { children: React.ReactNode }) {
  // AuthGate is a pass-through when Auth0 isn't configured.
  return (
    <AuthGate>
      <CopilotKit
        runtimeUrl={runtimeUrl()}
        useSingleEndpoint
        enableInspector={false}
      >
        <AppShell>{children}</AppShell>
      </CopilotKit>
    </AuthGate>
  )
}
