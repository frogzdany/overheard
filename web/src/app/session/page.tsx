"use client"

import { Suspense } from "react"
import { Flex, Spinner } from "@chakra-ui/react"
import { useSearchParams } from "next/navigation"
import { SessionDetailClient } from "./Client"

function SessionPageInner() {
  const params = useSearchParams()
  const id = params.get("id") ?? ""
  // Demo flag: `?mock=actions` seeds the session from a local fixture so the
  // Actions UI can be shown (and screenshotted) with no engine running.
  const mock = params.get("mock") === "actions"
  if (!id) {
    return (
      <Flex justify="center" py="20" color="fg.muted">
        Missing session id.
      </Flex>
    )
  }
  return <SessionDetailClient id={id} mock={mock} />
}

export default function SessionPage() {
  return (
    <Suspense fallback={<Flex justify="center" py="20"><Spinner /></Flex>}>
      <SessionPageInner />
    </Suspense>
  )
}
