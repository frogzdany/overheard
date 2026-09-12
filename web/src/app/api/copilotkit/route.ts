import {
  CopilotRuntime,
  OpenAIAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime"
import OpenAI from "openai"

export const runtime = "nodejs"

// Newest gpt-5 family entry on openai's ChatModel union (openai@7.15.0).
const DEFAULT_MODEL = "gpt-5.6-sol"

const copilotRuntime = new CopilotRuntime()

export const POST = async (req: Request) => {
  const apiKey = process.env.OPENAI_API_KEY
  if (!apiKey) {
    return Response.json(
      { error: "OPENAI_API_KEY is not set" },
      { status: 500 },
    )
  }
  const openai = new OpenAI({ apiKey })
  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime: copilotRuntime,
    serviceAdapter: new OpenAIAdapter({
      openai,
      model: process.env.COPILOT_MODEL || DEFAULT_MODEL,
    }),
    endpoint: "/api/copilotkit",
  })
  return handleRequest(req)
}
