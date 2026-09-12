"use client"

import { Box, Flex } from "@chakra-ui/react"
import { Sidebar } from "./Sidebar"
import { Header } from "./Header"

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <Flex minH="100vh" bg="bg">
      <Sidebar />
      <Flex direction="column" flex="1" minW="0">
        <Header />
        <Box as="main" flex="1" overflowY="auto" p="6">
          {children}
        </Box>
      </Flex>
    </Flex>
  )
}
