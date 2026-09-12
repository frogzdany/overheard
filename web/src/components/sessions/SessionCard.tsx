"use client"

import {
  Badge,
  Box,
  Flex,
  Heading,
  HStack,
  IconButton,
  Text,
} from "@chakra-ui/react"
import Link from "next/link"
import { LuClock, LuMessageCircle, LuTrash2, LuUsers } from "react-icons/lu"
import type { Session } from "@/types/session"
import type { SessionSummary } from "@/lib/engine"
import { formatDateTime } from "@/lib/format"

function formatDuration(sec: number) {
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

export function SessionCard({
  session,
  extra,
  onDelete,
}: {
  session: Session
  extra?: SessionSummary
  onDelete?: () => void
}) {
  const speakerNames = session.speakers
    .map((s) => s.label ?? `Speaker ${s.id}`)
    .join(" · ")
  const tags = extra?.tags?.filter((t) => t) ?? []

  return (
    <Link
      href={`/session?id=${encodeURIComponent(session.id)}`}
      style={{ textDecoration: "none", display: "block" }}
    >
      <Box
        position="relative"
        borderWidth="1px"
        borderColor="border"
        rounded="lg"
        bg="bg.panel"
        p="5"
        h="full"
        transition="all 0.15s"
        _hover={{ borderColor: "border.emphasized", shadow: "sm" }}
      >
        {onDelete ? (
          <IconButton
            position="absolute"
            top="2"
            right="2"
            size="xs"
            variant="ghost"
            colorPalette="red"
            aria-label="Delete session"
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              onDelete()
            }}
          >
            <LuTrash2 />
          </IconButton>
        ) : null}
        <Flex direction="column" gap="3" h="full">
          <Box>
            <Heading size="md" lineClamp={2}>
              {session.title}
            </Heading>
            <Flex align="center" gap="2" mt="1" fontSize="xs" color="fg.muted" wrap="wrap">
              <Text>{formatDateTime(session.startedAt)}</Text>
            </Flex>
          </Box>
          <Text fontSize="sm" color="fg.muted" lineClamp={3} flex="1">
            {session.summary.text}
          </Text>
          {tags.length ? (
            <Flex gap="1" wrap="wrap">
              {tags.slice(0, 4).map((t) => (
                <Badge key={t} variant="subtle" colorPalette="blue" fontSize="xs">
                  {t}
                </Badge>
              ))}
              {tags.length > 4 ? (
                <Badge variant="subtle" colorPalette="gray" fontSize="xs">
                  +{tags.length - 4}
                </Badge>
              ) : null}
            </Flex>
          ) : null}
          <HStack gap="4" pt="2" color="fg.muted" fontSize="xs">
            <HStack gap="1">
              <LuClock />
              <Text>{formatDuration(session.durationSec)}</Text>
            </HStack>
            <HStack gap="1">
              <LuUsers />
              <Text>{session.speakers.length}</Text>
            </HStack>
            <HStack gap="1">
              <LuMessageCircle />
              <Text>{session.questionCount} Q</Text>
            </HStack>
          </HStack>
          <Box>
            <Badge variant="subtle" colorPalette="gray" fontSize="xs">
              {speakerNames}
            </Badge>
          </Box>
        </Flex>
      </Box>
    </Link>
  )
}
