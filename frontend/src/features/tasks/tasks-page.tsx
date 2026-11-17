import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ViewSwitch } from "@/components/data-table/view-switch";
import { OpportunityKanban } from "@/features/opportunities/opportunity-kanban";
import "@/features/opportunities/opportunities.css";
import { api, useAuth } from "@/lib/auth-context";
import { CreateTask } from "./create-task";
import { TaskList } from "./task-list";
import { TaskDetail } from "./task-detail";
import { TaskTable } from "./task-table";
import {
  fetchTasks,
  saveTask,
  tasksHref,
  taskColumns,
  taskStatuses,
  type Task,
  type TaskPatch,
  type TaskView,
} from "./task-api";

function readRoute() {
  const query = new URLSearchParams(window.location.hash.split("?")[1]);
  const view = query.get("view");
  return {
    id: query.get("id"),
    opportunity: query.get("opportunity"),
    view: (view === "board" || view === "list" ? view : "table") as TaskView,
  };
}

export function TasksPage({
  workspace,
  userId,
}: {
  workspace: string;
  userId: string;
}) {
  const { active } = useAuth();
  const canEdit =
    active?.workspace_slug === workspace &&
    (active.role === "editor" || active.role === "admin");
  const [route, setRoute] = useState(readRoute);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [task, setTask] = useState<Task | null>(null);
  const [parent, setParent] = useState<{
    id: string;
    name: string;
    archived: boolean;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [saving, setSaving] = useState(false);
  const savePending = useRef(false);
  const [reload, setReload] = useState(0);
  const { id, opportunity, view } = route;

  useEffect(() => {
    const onRouteChange = () => setRoute(readRoute());
    window.addEventListener("hashchange", onRouteChange);
    return () => window.removeEventListener("hashchange", onRouteChange);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const options = { signal: controller.signal };
    setLoading(true);
    setLoadError("");
    setSaveError("");
    setTask(null);
    setParent(null);
    async function load() {
      try {
        if (id) {
          const detail = await api<Task>(
            `/tasks/${encodeURIComponent(id)}`,
            options,
            workspace,
          );
          if (!controller.signal.aborted) setTask(detail);
        } else {
          const [items, selectedParent] = await Promise.all([
            fetchTasks(workspace, opportunity, controller.signal),
            opportunity
              ? api<{ id: string; name: string; archived: boolean }>(
                  `/opportunities/${encodeURIComponent(opportunity)}`,
                  options,
                  workspace,
                )
              : null,
          ]);
          if (!controller.signal.aborted) {
            setTasks(items);
            setParent(selectedParent);
          }
        }
      } catch (err) {
        if (!controller.signal.aborted) setLoadError((err as Error).message);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [workspace, id, opportunity, reload]);

  async function update(item: Task, patch: TaskPatch) {
    if (savePending.current || !canEdit) return false;
    savePending.current = true;
    setSaving(true);
    setSaveError("");
    try {
      const updated = await saveTask(workspace, item, patch);
      setTask((current) => (current?.id === updated.id ? updated : current));
      setTasks((current) =>
        current.map((entry) => (entry.id === updated.id ? updated : entry)),
      );
      return true;
    } catch (err) {
      setSaveError((err as Error).message);
      return false;
    } finally {
      savePending.current = false;
      setSaving(false);
    }
  }

  if (loading)
    return (
      <p role="status" className="p-6 text-sm text-muted-foreground">
        Loading tasks…
      </p>
    );
  if (loadError)
    return (
      <div className="space-y-3 p-6">
        <p role="alert" className="text-sm text-destructive">
          {loadError}
        </p>
        <Button
          variant="outline"
          onClick={() => setReload((value) => value + 1)}
        >
          Retry
        </Button>
        <Button variant="ghost" asChild>
          <a href="#tasks">All tasks</a>
        </Button>
      </div>
    );
  if (id && task)
    return (
      <TaskDetail
        key={task.id}
        task={task}
        workspace={workspace}
        userId={userId}
        canEdit={canEdit}
        backHref={tasksHref({ opportunity, view })}
        saving={saving}
        error={saveError}
        onSave={update}
      />
    );
  const href = (item: Task) => tasksHref({ id: item.id, opportunity, view });
  const navigate = (next: { opportunity?: string | null; view?: TaskView }) => {
    window.location.hash = tasksHref({ opportunity, view, ...next });
  };
  const setView = (next: TaskView) => {
    navigate({ view: next });
  };
  return (
    <section
      aria-label="Workspace tasks"
      className="w-full min-w-0 space-y-4 p-4 sm:p-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ViewSwitch
          value={view}
          views={["table", "board", "list"]}
          onChange={setView}
          label="Task view"
        />
        {canEdit && !parent?.archived && (
          <CreateTask
            workspace={workspace}
            parent={parent ?? undefined}
            onCreated={(created) => {
              setTasks((current) => [
                created,
                ...current.filter((item) => item.id !== created.id),
              ]);
            }}
          />
        )}
      </div>
      {parent && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <a
            className="font-medium hover:underline"
            href={`#opportunities?id=${encodeURIComponent(parent.id)}`}
          >
            {parent.name}
          </a>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => navigate({ opportunity: null })}
          >
            Show all tasks
          </Button>
        </div>
      )}
      {saveError && (
        <p role="alert" className="text-sm text-destructive">
          {saveError}
        </p>
      )}
      {saving && (
        <p role="status" className="text-sm text-muted-foreground">
          Saving task…
        </p>
      )}
      <TaskTable
        onBulkStatus={async (selected, status) => {
          const saved: string[] = [];
          for (const item of selected) {
            if (!(await update(item, { status }))) break;
            saved.push(item.id);
          }
          return saved;
        }}
        tasks={tasks}
        href={href}
        canEdit={canEdit}
        saving={saving}
        onStatus={(item, status) => void update(item, { status })}
      >
        {view === "table"
          ? undefined
          : (visible) => (
              <>
                {view === "list" && (
                  <TaskList
                    tasks={visible}
                    href={href}
                    showOpportunity={!parent}
                  />
                )}
                {view === "board" && (
                  <OpportunityKanban
                    items={visible.map((item) => ({
                      id: item.id,
                      name: item.title,
                      status: item.status,
                      priority: null,
                      created_at: item.created_at,
                      feedback_count: 0,
                    }))}
                    allItems={visible.map((item) => ({
                      id: item.id,
                      name: item.title,
                      status: item.status,
                      priority: null,
                      created_at: item.created_at,
                      feedback_count: 0,
                    }))}
                    view="board"
                    boardColumns={taskColumns}
                    disabled={!canEdit || saving}
                    dropLabel="Drop a task here"
                    readOnlyInstructions={
                      saving
                        ? "Saving task…"
                        : "Open a task to see its details."
                    }
                    instructions="Drag tasks between lanes to change their status."
                    onOpen={(taskId) => {
                      window.location.hash = tasksHref({
                        id: taskId,
                        opportunity,
                        view,
                      });
                    }}
                    renderCardMetadata={(card) => {
                      const item = visible.find(
                        (entry) => entry.id === card.id,
                      );
                      return (
                        item && (
                          <div className="min-w-0 text-xs text-muted-foreground">
                            {!parent && (
                              <p
                                className="truncate"
                                title={item.opportunity_name}
                              >
                                {item.opportunity_name}
                              </p>
                            )}
                            <p
                              className="truncate"
                              title={item.assignee_name ?? undefined}
                            >
                              {item.assignee_name ?? "Unassigned"}
                            </p>
                          </div>
                        )
                      );
                    }}
                    onCommit={async (moved) => {
                      const change = moved.find((entry) =>
                        visible.some(
                          (item) =>
                            item.id === entry.id &&
                            item.status !== entry.status,
                        ),
                      );
                      if (
                        !change ||
                        !Object.hasOwn(taskStatuses, change.status)
                      )
                        return false;
                      const item = visible.find(
                        (entry) => entry.id === change.id,
                      );
                      return item
                        ? update(item, {
                            status: change.status as Task["status"],
                          })
                        : false;
                    }}
                  />
                )}
              </>
            )}
      </TaskTable>
    </section>
  );
}
