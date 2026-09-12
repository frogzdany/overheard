// Loads environment variables from local .env files before anything else in the
// process reads process.env. Import this module first (for its side effect) from
// any entry point that needs the keys: the HTTP server (src/server.ts) and the
// Trigger.dev task entry (src/trigger/execute-action.ts).
//
// Load order (first file wins; a variable already present in the real process
// environment is never overridden by either file):
//   1. hands/.env       (this package's own overrides)
//   2. ../.env          (the repo root .env, shared across overheard services)
//
// Paths are resolved from process.cwd() rather than import.meta.url because every
// entry point that imports this module is always started with the hands/
// directory as its working directory (npm scripts, `npx tsx src/server.ts`,
// `npx tsx scripts/*.ts`, and the Trigger.dev CLI all run with cwd = hands/) —
// the same convention already used for .hands-claims.json and
// .hands-run-tokens.json elsewhere in this package.
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";

import { config as loadDotenvFile } from "dotenv";

const HANDS_DIR = process.cwd();
const ROOT_DIR = resolve(HANDS_DIR, "..");

const candidates = [join(HANDS_DIR, ".env"), join(ROOT_DIR, ".env")];
const foundEnvFiles: string[] = [];

for (const path of candidates) {
  if (existsSync(path)) {
    loadDotenvFile({ path, override: false, quiet: true });
    foundEnvFiles.push(path);
  }
}

console.info(
  foundEnvFiles.length > 0
    ? `[hands] env files loaded (in order): ${foundEnvFiles.join(", ")}`
    : "[hands] no .env files found at hands/.env or ../.env; using process environment only",
);
