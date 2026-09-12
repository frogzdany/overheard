// `npx trigger.dev@latest dev` already auto-loads .env / .env.local (etc.) from
// this package's own directory (hands/) before running task code, but it does
// NOT read the repo root ../.env. This side-effect import additionally loads
// ../.env (without overriding hands/.env or already-set variables) so the
// shared root keys (EXA_API_KEY, AMBIGUOUS_API_KEY, ...) reach trigger-mode
// runs too, without having to duplicate them into hands/.env. See ../env.ts.
import "../env.js";

import { task, wait } from "@trigger.dev/sdk";

import { executeAction, reportStatus } from "../execute.js";
import { actionSchema, suggestedActionSchema, type Action } from "../schema.js";

export const executeActionTask = task({
  id: "execute-action",
  run: async (payload: { action: unknown; waitToken?: string }, { ctx }) => {
    if (payload.waitToken) {
      const suggestedAction = suggestedActionSchema.parse(payload.action);
      const result = await wait.forToken<{ approved: boolean; action?: Action }>(payload.waitToken);
      if (!result.ok) {
        await reportStatus(suggestedAction, {
          status: "failed",
          runId: ctx.run.id,
          error: "approval timed out",
        });
        return;
      }
      if (!result.output.approved) return;

      const approvedAction = actionSchema.parse(result.output.action);
      return executeAction(approvedAction, ctx.run.id);
    }

    const action = actionSchema.parse(payload.action);
    return executeAction(action, ctx.run.id);
  },
});
