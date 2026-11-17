import { openRecords } from "./assistant-actions";
import { api, apiRequest } from "./auth-context";
import {
  readAssistantEvents,
  type AssistantConfig,
  type AssistantEvent,
} from "./assistant-contracts";

export async function runAssistant(
  message: string,
  workspace: string,
  signal: AbortSignal,
  receive: (event: AssistantEvent) => void,
  config: AssistantConfig,
  context?: { kind: "feedback" | "opportunity"; id: string },
) {
  const response = await apiRequest(
    "/assistant/runs",
    { method: "POST", body: JSON.stringify({ message, context }), signal },
    workspace,
  );
  if (!response.body) throw new Error("The assistant stream is unavailable.");
  let completed = false;
  for await (const event of readAssistantEvents(response.body, signal)) {
    if (signal.aborted) return;
    if (event.type === "action") {
      receive({
        type: "status",
        message: "Opening the filtered Records view…",
      });
      const ok = await openRecords(
        workspace,
        event.query,
        signal,
        config.navigation_timeout_ms,
      );
      if (signal.aborted) return;
      await api(
        `/assistant/runs/${encodeURIComponent(event.run_id)}/actions`,
        {
          method: "POST",
          body: JSON.stringify({ action_id: event.action_id, ok }),
          signal,
        },
        workspace,
      );
    } else if (event.type === "error") {
      throw new Error(event.message || "The assistant request failed.");
    } else {
      receive(event);
      if (event.type === "done") {
        completed = true;
        if (event.error)
          throw new Error(
            "The agent reached a limit or could not finish. No records were changed.",
          );
        break;
      }
    }
  }
  if (!completed && !signal.aborted)
    throw new Error("The assistant connection ended before completion.");
}
