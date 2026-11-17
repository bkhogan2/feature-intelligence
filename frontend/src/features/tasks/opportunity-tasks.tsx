import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import { CreateTask } from "./create-task";
import { fetchTasks, tasksHref, type Task } from "./task-api";
import { TaskList } from "./task-list";

export function OpportunityTasks({
  id,
  name,
  workspace,
  canAdd,
  actionTarget,
}: {
  id: string;
  name: string;
  workspace: string;
  canAdd: boolean;
  actionTarget: HTMLDivElement | null;
}) {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [error, setError] = useState("");
  const boardHref = tasksHref({ opportunity: id, view: "board" });

  useEffect(() => {
    const controller = new AbortController();
    fetchTasks(workspace, id, controller.signal)
      .then((items) => {
        if (!controller.signal.aborted) {
          setTasks((current) => [
            ...(current ?? []).filter(
              (task) => !items.some((item) => item.id === task.id),
            ),
            ...items,
          ]);
        }
      })
      .catch((err: Error) => {
        if (!controller.signal.aborted) setError(err.message);
      });
    return () => controller.abort();
  }, [id, workspace]);

  return (
    <section aria-label="Opportunity tasks" className="issue-review space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">Tasks</h2>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="ghost" asChild>
            <a href={boardHref}>View on board</a>
          </Button>
        </div>
      </div>
      {canAdd &&
        actionTarget &&
        createPortal(
          <CreateTask
            workspace={workspace}
            parent={{ id, name }}
            boardHref={boardHref}
            onCreated={(task) =>
              setTasks((current) => [
                task,
                ...(current ?? []).filter((item) => item.id !== task.id),
              ])
            }
          />,
          actionTarget,
        )}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : tasks === null ? (
        <p role="status" className="text-sm text-muted-foreground">
          Loading tasks…
        </p>
      ) : (
        <TaskList
          tasks={tasks}
          showProgress
          href={(task) => tasksHref({ id: task.id })}
        />
      )}
    </section>
  );
}
