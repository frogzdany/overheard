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
