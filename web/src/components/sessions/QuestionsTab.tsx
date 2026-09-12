"use client"

import { memo, useState } from "react"
import {
  Alert,
  Box,
  Button,
  Flex,
  Heading,
  Stack,
  Text,
} from "@chakra-ui/react"

// Surface only the most recent N by default. The insight worker re-emits
// the full list every pass, so without a cap every refresh repaints every
// question card. The user can still see the rest behind "Show all".
const VISIBLE_QUESTIONS = 8
import { engineApi, type QuestionForMe } from "@/lib/engine"
import type { QuestionAnswer } from "@/types/session"

interface Props {
  sessionId: string
  qa: QuestionAnswer[]
  /** Questions the engine judged were directed at the user (curated, deduped). */
  questionsForMe: QuestionForMe[]
}

const QuestionCard = memo(function QuestionCard({
  question,
  action,
}: {
  question: string
  action?: React.ReactNode
}) {
  return (
    <Box
      p="4"
      borderWidth="1px"
      borderColor="border"
      rounded="md"
      bg="bg.panel"
    >
      <Flex align="flex-start" justify="space-between" gap="3">
        <Text fontWeight="medium" flex="1">{question}</Text>
        {action ? <Flex gap="2">{action}</Flex> : null}
      </Flex>
    </Box>
  )
})

export function QuestionsTab({ sessionId, qa, questionsForMe }: Props) {
  const [showAll, setShowAll] = useState(false)
  const [dismissed, setDismissed] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  const mine = questionsForMe.filter((q) => !dismissed.includes(q.id))

  const dismiss = async (qid: string) => {
    setDismissed((cur) => [...cur, qid])
    setError(null)
    try {
      await engineApi.dismissQuestionForMe(sessionId, qid)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  if (!qa.length && !mine.length) {
    return (
      <Box py="10" textAlign="center" color="fg.muted">
        <Text>No questions surfaced yet.</Text>
        <Text fontSize="sm" mt="2">
          Questions detected in the transcript will appear here, and anything
          asked directly of you is called out at the top.
        </Text>
      </Box>
    )
  }

  return (
    <Stack gap="4">
      {error ? (
        <Alert.Root status="error">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>Could not dismiss the question</Alert.Title>
            <Alert.Description>{error}</Alert.Description>
          </Alert.Content>
        </Alert.Root>
      ) : null}

      {mine.length ? (
        <Stack gap="3">
          <Heading size="sm">Asked of you</Heading>
          {mine.map((q) => (
            <QuestionCard
              key={q.id}
              question={q.text}
              action={
                <Button size="sm" variant="outline" onClick={() => dismiss(q.id)}>
                  Dismiss
                </Button>
              }
            />
          ))}
        </Stack>
      ) : null}

      {qa.length ? (
        <>
          <Flex align="center" justify="space-between" gap="3" wrap="wrap">
            <Text fontSize="sm" color="fg.muted">
              Surfaced from transcript ({qa.length}).
            </Text>
            {qa.length > VISIBLE_QUESTIONS ? (
              <Button
                size="xs"
                variant="ghost"
                onClick={() => setShowAll((v) => !v)}
              >
                {showAll
                  ? `Show recent ${VISIBLE_QUESTIONS}`
                  : `Show all (${qa.length})`}
              </Button>
            ) : null}
          </Flex>

          <Stack gap="3">
            {(showAll ? qa : qa.slice(-VISIBLE_QUESTIONS))
              .slice()
              .reverse()
              .map((q) => (
                <QuestionCard key={q.question} question={q.question} />
              ))}
          </Stack>
        </>
      ) : null}
    </Stack>
  )
}
