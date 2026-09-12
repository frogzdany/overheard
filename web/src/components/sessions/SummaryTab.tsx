"use client"

import { Badge, Box, Heading, Stack, Text } from "@chakra-ui/react"
import { Markdown } from "@/components/Markdown"
import { formatEngineTime } from "@/lib/format"

export function SummaryTab({
  summary,
  archive,
}: {
  // `updatedAt` arrives as unix SECONDS from the live bus event and as an
  // ISO-8601 string from GET /sessions/{id}; formatEngineTime takes either.
  // Formatting it as seconds only rendered the REST value as an em dash.
  summary: { text: string; updatedAt: number | string | null; forcedFinal: boolean } | null
  archive: string | null
}) {
  if (!summary?.text && !archive) {
    return (
      <Box py="10" textAlign="center" color="fg.muted">
        <Text>Summary will appear here once the engine produces its first update (~45s).</Text>
      </Box>
    )
  }

  return (
    <Stack gap="4">
      {summary?.text ? (
        <Box
          p="5"
          borderWidth="1px"
          borderColor="border"
          rounded="md"
          bg="bg.panel"
        >
          <Box mb="3">
            <Heading size="sm">Rolling summary</Heading>
            {summary.updatedAt ? (
              <Text fontSize="xs" color="fg.muted" mt="1">
                Updated {formatEngineTime(summary.updatedAt)} UTC
                {summary.forcedFinal ? (
                  <Badge ml="2" colorPalette="green">final</Badge>
                ) : null}
              </Text>
            ) : null}
          </Box>
          <Markdown>{summary.text}</Markdown>
        </Box>
      ) : null}

      {archive ? (
        <Box
          p="5"
          borderWidth="1px"
          borderColor="border"
          rounded="md"
          bg="bg.subtle"
        >
          <Heading size="sm" mb="3">
            Archive transcript
          </Heading>
          <Markdown>{archive}</Markdown>
        </Box>
      ) : null}
    </Stack>
  )
}
