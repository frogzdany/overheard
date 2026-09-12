// Live connectivity check for the Exa connector. Calls answer() through
// src/connectors/exa.ts exactly as the `lookup` action does, and prints the
// first 200 characters of the answer plus the citation count (or the error).
//
// Run with: npx tsx scripts/check-exa.ts
import "../src/env.js";

import { answer } from "../src/connectors/exa.js";

function mask(value: string): string {
  return value.length <= 4 ? `${value}****` : `${value.slice(0, 4)}****`;
}

async function main(): Promise<void> {
  const apiKey = process.env.EXA_API_KEY?.trim();
  if (!apiKey) {
    console.error("[check-exa] EXA_API_KEY is not set (checked hands/.env, ../.env, and shell env)");
    process.exitCode = 1;
    return;
  }

  console.info(`[check-exa] API key: ${mask(apiKey)}`);

  try {
    const result = await answer("What is Trigger.dev?");
    console.info(`\n[check-exa] First 200 chars of answer:\n${result.answer.slice(0, 200)}`);
    console.info(`\n[check-exa] Citation count: ${result.citations.length}`);
  } catch (error) {
    console.error("\n[check-exa] answer() failed:");
    console.error(`  ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  }
}

void main();
