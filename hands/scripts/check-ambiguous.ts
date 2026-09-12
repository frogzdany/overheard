// Live connectivity check for the Ambiguous MCP connector. Connects exactly the
// way src/connectors/ambiguous.ts does (same Client / StreamableHTTPClientTransport
// / Authorization header), calls tools/list, prints the advertised tool names, and
// reports how each of our five logical tools resolves against them (or the error).
//
// This script only calls tools/list — it never invokes a tool, so it has no
// side effects in the connected Ambiguous workspace.
//
// Run with: npx tsx scripts/check-ambiguous.ts
import "../src/env.js";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

import { resolveToolName, type LogicalTool } from "../src/connectors/ambiguous.js";

function mask(value: string): string {
  return value.length <= 4 ? `${value}****` : `${value.slice(0, 4)}****`;
}

// The five logical "tools" we resolve. `lookup` isn't its own Ambiguous tool:
// per src/execute.ts's dispatch(), the `lookup` action kind calls Exa for the
// answer and then files it away via the same docs.create tool as "docs.create".
const LOGICAL_TOOLS: LogicalTool[] = [
  "tasks.create",
  "calendar.createEvent",
  "chat.sendMessage",
  "docs.create",
];

async function main(): Promise<void> {
  const apiKey = process.env.AMBIGUOUS_API_KEY?.trim();
  const mcpUrl = process.env.AMBIGUOUS_MCP_URL || "https://app.ambiguous.ai/mcp";

  if (!apiKey) {
    console.error("[check-ambiguous] AMBIGUOUS_API_KEY is not set (checked hands/.env, ../.env, and shell env)");
    process.exitCode = 1;
    return;
  }

  console.info(`[check-ambiguous] MCP URL: ${mcpUrl}`);
  console.info(`[check-ambiguous] API key: ${mask(apiKey)}`);

  const transport = new StreamableHTTPClientTransport(new URL(mcpUrl), {
    requestInit: { headers: { Authorization: `Bearer ${apiKey}` } },
  });
  const client = new Client({ name: "overheard-hands-check", version: "0.1.0" });

  try {
    await client.connect(transport);
    const listed = await client.listTools();
    const names = listed.tools.map((tool) => tool.name);

    console.info(`\n[check-ambiguous] tools/list returned ${names.length} tool(s):`);
    for (const name of names) console.info(`  - ${name}`);

    console.info("\n[check-ambiguous] Logical tool resolution:");
    for (const logical of LOGICAL_TOOLS) {
      try {
        const resolved = resolveToolName(logical, names);
        console.info(`  ${logical.padEnd(20)} -> ${resolved}`);
      } catch (error) {
        console.info(`  ${logical.padEnd(20)} -> ERROR: ${error instanceof Error ? error.message : String(error)}`);
      }
    }

    // The `lookup` action kind resolves via docs.create (see src/execute.ts dispatch()).
    try {
      const resolved = resolveToolName("docs.create", names);
      console.info(`  ${"lookup (-> docs.create)".padEnd(20)} -> ${resolved}`);
    } catch (error) {
      console.info(
        `  ${"lookup (-> docs.create)".padEnd(20)} -> ERROR: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  } catch (error) {
    console.error("\n[check-ambiguous] connection or tools/list failed:");
    if (error && typeof error === "object") {
      const status = (error as { status?: number; code?: number }).status ?? (error as { code?: number }).code;
      if (status) console.error(`  HTTP status: ${status}`);
      const body = (error as { body?: unknown; responseText?: string }).body ??
        (error as { responseText?: string }).responseText;
      if (body) console.error(`  Body: ${typeof body === "string" ? body : JSON.stringify(body)}`);
    }
    console.error(`  ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  } finally {
    await client.close().catch(() => {});
  }
}

void main();
