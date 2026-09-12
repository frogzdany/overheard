"use client"

import { Flex, Heading, Spacer } from "@chakra-ui/react"
import { usePathname } from "next/navigation"
import { ColorModeButton } from "@/components/ui/color-mode"

// Title derived from the current route so the AppShell header reflects what
// page the user is on (Sessions / a specific Session).
function titleFor(pathname: string): string {
  if (pathname.startsWith("/session")) return "Session"
  return "Sessions"
}

export function Header() {
  const pathname = usePathname() ?? "/"
  return (
    <Flex
      as="header"
      align="center"
      px="6"
      py="4"
      borderBottomWidth="1px"
      borderColor="border"
      bg="bg"
      position="sticky"
      top="0"
      zIndex="1"
    >
      <Heading size="lg">{titleFor(pathname)}</Heading>
      <Spacer />
      <ColorModeButton />
    </Flex>
  )
}
