import { defineConfig } from "@trigger.dev/sdk";

export default defineConfig({
  project: process.env.TRIGGER_PROJECT_REF || "proj_dojlvegbfiagagjoshjt",
  runtime: "node",
  dirs: ["./src/trigger"],
  maxDuration: 3_900,
});
