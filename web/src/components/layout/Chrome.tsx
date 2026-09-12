"use client"

import { CopilotKit } from "@copilotkit/react-core"
import { AppShell } from "./AppShell"
import { AuthGate } from "@/components/auth/AuthGate"

export function Chrome({ children }: { children: React.ReactNode }) {
  // AuthGate is a pass-through when Auth0 isn't configured.
  return (
    <AuthGate>
      <CopilotKit
        runtimeUrl="/api/copilotkit"
        useSingleEndpoint
        enableInspector={false}
      >
        <AppShell>{children}</AppShell>
      </CopilotKit>
    </AuthGate>
  )
}
