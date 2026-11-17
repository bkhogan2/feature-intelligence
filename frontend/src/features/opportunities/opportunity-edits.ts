import { api } from "@/lib/auth-context";
import type { PriorityFields } from "./priority-section";

export const priorities = ["high", "medium", "low"] as const;

export const lifecycleLabels = {
  considering: "Considering",
  planned: "Planned",
  in_progress: "In progress",
  shipped: "Shipped",
  not_pursuing: "Not pursuing",
} satisfies Record<string, string>;

export function saveOpportunityStatus<T>(
  workspace: string,
  id: string,
  status: string,
  expectedStatus: string,
  note = "",
) {
  return api<T>(
    `/opportunities/${id}/decisions`,
    {
      method: "POST",
      body: JSON.stringify({ status, expected_status: expectedStatus, note }),
    },
    workspace,
  );
}

export function saveManualPriority(
  workspace: string,
  detail: Pick<
    PriorityFields,
    "id" | "priority_revision" | "effort" | "dependencies"
  >,
  priority: (typeof priorities)[number],
) {
  return api<PriorityFields>(
    `/opportunities/${detail.id}/priority`,
    {
      method: "PUT",
      body: JSON.stringify({
        priority,
        rationale: `Manually set to ${priority}.`,
        expected_revision: detail.priority_revision,
        effort: detail.effort,
        dependencies: detail.dependencies,
      }),
    },
    workspace,
  );
}
