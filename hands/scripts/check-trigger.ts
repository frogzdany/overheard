// Verifies TRIGGER_SECRET_KEY + TRIGGER_PROJECT_REF against the Trigger.dev API. Prints no secrets.
import "../src/env.js";
import { configure, runs } from "@trigger.dev/sdk";
const key = process.env.TRIGGER_SECRET_KEY || "";
if (!key) { console.error("TRIGGER_SECRET_KEY is not set"); process.exit(1); }
configure({ secretKey: key });
const page = await runs.list({ limit: 1 });
console.log(`trigger api ok (key ${key.slice(0, 7)}…, project ${process.env.TRIGGER_PROJECT_REF || "unset"}), runs visible: ${page.data.length}`);
