import { z } from "zod";

export const actionKindSchema = z.enum([
  "create_task",
  "schedule_followup",
  "draft_message",
  "create_doc",
  "lookup",
]);

const actionBaseSchema = z.object({
  id: z.string().min(1),
  sessionId: z.string().min(1),
  kind: actionKindSchema,
  title: z.string().min(1),
  rationale: z.string(),
  evidence: z.array(z.string()),
  confidence: z.number().min(0).max(1),
  tool: z.string().min(1),
  args: z.record(z.unknown()),
  runId: z.string().nullable(),
  resultUrl: z.string().nullable(),
  suggestedAt: z.string().datetime({ offset: true }).optional(),
});

export const actionSchema = actionBaseSchema.extend({
  status: z.literal("approved"),
  approvedBy: z.string().min(1),
});

export const suggestedActionSchema = actionBaseSchema.extend({
  status: z.literal("suggested"),
  approvedBy: z.null().optional(),
});

export const statusCallbackSchema = z.object({
  status: z.enum(["running", "succeeded", "failed"]),
  runId: z.string(),
  resultUrl: z.string().optional(),
  error: z.string().optional(),
});

export type Action = z.infer<typeof actionSchema>;
export type SuggestedAction = z.infer<typeof suggestedActionSchema>;
export type StatusCallback = z.infer<typeof statusCallbackSchema>;
