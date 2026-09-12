"use client"

import {
  Box,
  Code,
  Heading,
  Link,
  List,
  Text,
} from "@chakra-ui/react"
import ReactMarkdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"

const components: Components = {
  h1: ({ children }) => (
    <Heading as="h1" size="lg" mt="4" mb="3">
      {children}
    </Heading>
  ),
  h2: ({ children }) => (
    <Heading as="h2" size="md" mt="4" mb="2">
      {children}
    </Heading>
  ),
  h3: ({ children }) => (
    <Heading as="h3" size="sm" mt="3" mb="2">
      {children}
    </Heading>
  ),
  p: ({ children }) => (
    <Text mb="2" lineHeight="tall">
      {children}
    </Text>
  ),
  a: ({ href, children }) => (
    <Link href={href} colorPalette="blue" target="_blank" rel="noreferrer">
      {children}
    </Link>
  ),
  ul: ({ children }) => (
    <List.Root pl="6" mb="3">
      {children}
    </List.Root>
  ),
  ol: ({ children }) => (
    <List.Root as="ol" pl="6" mb="3">
      {children}
    </List.Root>
  ),
  li: ({ children }) => <List.Item>{children}</List.Item>,
  code: ({ children, className }) => {
    const isBlock = (className ?? "").startsWith("language-")
    if (isBlock) {
      return (
        <Box
          as="pre"
          bg="bg.subtle"
          p="3"
          rounded="md"
          overflowX="auto"
          fontSize="sm"
          fontFamily="mono"
          mb="3"
        >
          <code>{children}</code>
        </Box>
      )
    }
    return (
      <Code fontSize="sm" px="1.5" py="0.5">
        {children}
      </Code>
    )
  },
  hr: () => <Box as="hr" my="4" borderColor="border" />,
  blockquote: ({ children }) => (
    <Box
      borderLeftWidth="3px"
      borderColor="border.emphasized"
      pl="3"
      color="fg.muted"
      mb="3"
    >
      {children}
    </Box>
  ),
  strong: ({ children }) => <Text as="strong" fontWeight="semibold">{children}</Text>,
  em: ({ children }) => <Text as="em">{children}</Text>,
  table: ({ children }) => (
    <Box overflowX="auto" mb="3">
      <Box as="table" borderCollapse="collapse" width="full">
        {children}
      </Box>
    </Box>
  ),
  th: ({ children }) => (
    <Box as="th" textAlign="left" px="2" py="1" borderBottomWidth="1px" borderColor="border">
      {children}
    </Box>
  ),
  td: ({ children }) => (
    <Box as="td" px="2" py="1" borderBottomWidth="1px" borderColor="border">
      {children}
    </Box>
  ),
}

export function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {children}
    </ReactMarkdown>
  )
}
