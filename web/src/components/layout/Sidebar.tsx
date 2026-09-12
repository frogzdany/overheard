"use client"

import { Box, Flex, Heading, Stack, Text } from "@chakra-ui/react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { LuList } from "react-icons/lu"

const NAV: {
  href: string
  label: string
  icon: typeof LuList
}[] = [{ href: "/", label: "Sessions", icon: LuList }]

export function Sidebar() {
  const pathname = usePathname()
  const nav = NAV
  return (
    <Flex
      as="aside"
      direction="column"
      w="60"
      h="100vh"
      borderRightWidth="1px"
      borderColor="border"
      bg="bg.subtle"
      px="4"
      py="6"
      gap="6"
      position="sticky"
      top="0"
    >
      <Box>
        <Heading size="md">Overheard</Heading>
        <Text fontSize="xs" color="fg.muted">
          Real-time transcripts
        </Text>
      </Box>
      <Stack as="nav" gap="1">
        {nav.map(({ href, label, icon: Icon }) => {
          // Root entry only matches the home path exactly so it doesn't light
          // up on every other route. Non-root entries match by prefix so
          // nested pages keep them active.
          const active =
            href === "/" ? pathname === "/" : pathname.startsWith(href)
          return (
            <Link key={href} href={href} style={{ textDecoration: "none" }}>
              <Flex
                align="center"
                gap="3"
                px="3"
                py="2"
                rounded="md"
                bg={active ? "bg.emphasized" : "transparent"}
                color={active ? "fg" : "fg.muted"}
                _hover={{ bg: "bg.emphasized", color: "fg" }}
              >
                <Icon />
                <Text fontSize="sm" fontWeight="medium">
                  {label}
                </Text>
              </Flex>
            </Link>
          )
        })}
      </Stack>
    </Flex>
  )
}
