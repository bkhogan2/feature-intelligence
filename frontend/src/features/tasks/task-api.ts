import { api } from "@/lib/auth-context";
import { loadOpportunityPages } from "@/features/opportunities/opportunity-pagination";

export const taskStatuses = {
  backlog: "Backlog",
  todo: "To do",
  in_progress: "In progress",
  blocked: "Blocked",
  done: "Done",
} as const;

export type TaskStatus = keyof typeof taskStatuses;
export const taskColumns = Object.entries(taskStatuses).map(([id, name]) => ({
  id,
  name,
}));

export type Task = {
  id: string;
  opportunity_id: string;
  opportunity_name: string;
  title: string;
  description: string;
  status: TaskStatus;
  assignee_id: string | null;
  assignee_name: string | null;
  created_at: string;
  created_by: string;
  revision: number;
};

export type TaskPatch = Partial<
  Pick<Task, "title" | "description" | "status" | "assignee_id">
>;
export type TaskView = "table" | "board" | "list";

export function tasksHref(
  options: {
    opportunity?: string | null;
    view?: TaskView;
    id?: string | null;
  } = {},
) {
  const query = new URLSearchParams();
  if (options.opportunity) query.set("opportunity", options.opportunity);
  if (options.view && options.view !== "table") query.set("view", options.view);
  if (options.id) query.set("id", options.id);
  return query.size ? `#tasks?${query}` : "#tasks";
}

export function fetchTasks(
  workspace: string,
  opportunity: string | null,
  signal: AbortSignal,
) {
  return loadOpportunityPages<Task>((offset) => {
    const query = new URLSearchParams({ limit: "100", offset: String(offset) });
    if (opportunity) query.set("opportunity_id", opportunity);
    return api(`/tasks?${query}`, { signal }, workspace);
  });
}

export function saveTask(workspace: string, task: Task, patch: TaskPatch) {
  return api<Task>(
    `/tasks/${task.id}`,
    {
      method: "PATCH",
      body: JSON.stringify({ ...patch, expected_revision: task.revision }),
    },
    workspace,
  );
}
