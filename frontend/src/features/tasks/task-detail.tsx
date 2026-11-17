import { useEffect, useState } from "react";
import { Button as PrimerButton } from "@primer/react";
import {
  IssueComment,
  IssueDetail,
  IssueProperty,
} from "@/components/issue-detail/issue-detail";
import { IssueDiscussion } from "@/components/issue-detail/issue-discussion";
import { IssueMarkdownEditor } from "@/components/issue-detail/issue-markdown-editor";
import { AnalysisMarkdown } from "@/features/analysis/analysis-markdown";
import { api } from "@/lib/auth-context";
import { TaskStatusSelect } from "./task-list";
import { taskStatuses, type Task, type TaskPatch } from "./task-api";

type Member = { id: string; name: string };
type EditDraft = Pick<Task, "title" | "description" | "revision">;

export function TaskDetail({
  task,
  workspace,
  userId,
  canEdit,
  backHref,
  saving,
  error,
  onSave,
}: {
  task: Task;
  workspace: string;
  userId: string;
  canEdit: boolean;
  backHref: string;
  saving: boolean;
  error: string;
  onSave: (task: Task, patch: TaskPatch) => Promise<boolean>;
}) {
  const [members, setMembers] = useState<Member[]>([]);
  const [membersReady, setMembersReady] = useState(false);
  const [membersError, setMembersError] = useState("");
  const [draft, setDraft] = useState<EditDraft | null>(null);
  const [preview, setPreview] = useState(false);
  const titleValid = Boolean(draft?.title.trim());

  useEffect(() => {
    if (!canEdit) return;
    const controller = new AbortController();
    api<{ items: Member[] }>(
      "/tasks/assignees",
      { signal: controller.signal },
      workspace,
    )
      .then(({ items }) => {
        if (controller.signal.aborted) return;
        setMembers(items);
        setMembersReady(true);
      })
      .catch((err: Error) => {
        if (!controller.signal.aborted) setMembersError(err.message);
      });
    return () => controller.abort();
  }, [workspace, canEdit]);

  return (
    <IssueDetail
      id={task.id}
      title={task.title}
      status={taskStatuses[task.status]}
      backHref={backHref}
      backLabel="Tasks"
      subtitle={`Created ${new Date(task.created_at).toLocaleDateString()}`}
      sidebar={
        <>
          <IssueProperty label="Opportunity">
            <a
              href={`#opportunities?id=${encodeURIComponent(task.opportunity_id)}`}
            >
              {task.opportunity_name}
            </a>
          </IssueProperty>
          <IssueProperty label="Status">
            {canEdit ? (
              <TaskStatusSelect
                label="Task status"
                status={task.status}
                disabled={saving}
                onChange={(status) => void onSave(task, { status })}
              />
            ) : (
              taskStatuses[task.status]
            )}
          </IssueProperty>
          <IssueProperty label="Assignee">
            {canEdit && membersReady ? (
              <select
                aria-label="Task assignee"
                className="w-full rounded-md border bg-background p-2 text-sm"
                value={task.assignee_id ?? ""}
                disabled={saving}
                onChange={(event) =>
                  void onSave(task, { assignee_id: event.target.value || null })
                }
              >
                <option value="">Unassigned</option>
                {task.assignee_id &&
                  !members.some((member) => member.id === task.assignee_id) && (
                    <option value={task.assignee_id} disabled>
                      {task.assignee_name ?? "Former member"}
                    </option>
                  )}
                {members.map((member) => (
                  <option key={member.id} value={member.id}>
                    {member.name}
                  </option>
                ))}
              </select>
            ) : (
              (task.assignee_name ?? "Unassigned")
            )}
            {membersError && (
              <p role="alert" className="mt-2 text-sm text-destructive">
                {membersError}
              </p>
            )}
          </IssueProperty>
        </>
      }
    >
      {error && (
        <p role="alert" className="mb-3 text-sm text-destructive">
          {error}
        </p>
      )}
      <IssueComment
        author={task.created_by === userId ? "You" : "Workspace member"}
        date={task.created_at}
        label="Task description"
        headerActions={
          canEdit &&
          !draft && (
            <PrimerButton
              size="small"
              variant="invisible"
              onClick={() => {
                setPreview(false);
                setDraft({
                  title: task.title,
                  description: task.description,
                  revision: task.revision,
                });
              }}
            >
              Edit task
            </PrimerButton>
          )
        }
      >
        {draft ? (
          <form
            className="issue-comment-editor space-y-3"
            onSubmit={async (event) => {
              event.preventDefault();
              if (!titleValid || saving || !canEdit) return;
              const ok = await onSave(
                { ...task, revision: draft.revision },
                {
                  title: draft.title.trim(),
                  description: draft.description,
                },
              );
              if (ok) setDraft(null);
            }}
          >
            <label className="block space-y-1 text-sm font-medium">
              <span>Title</span>
              <input
                className="block w-full rounded-md border bg-background p-2"
                value={draft.title}
                onChange={(event) =>
                  setDraft({ ...draft, title: event.target.value })
                }
                maxLength={160}
                required
                disabled={saving}
              />
            </label>
            <IssueMarkdownEditor
              label="Description"
              body={draft.description}
              onChange={(description) => setDraft({ ...draft, description })}
              preview={preview}
              setPreview={setPreview}
              disabled={saving}
              maxLength={20000}
            />
            <div className="issue-comment-submit gap-2">
              <PrimerButton
                type="button"
                disabled={saving}
                onClick={() => setDraft(null)}
              >
                Cancel
              </PrimerButton>
              <PrimerButton
                type="submit"
                variant="primary"
                disabled={saving || !titleValid}
              >
                Save task
              </PrimerButton>
            </div>
          </form>
        ) : (
          <AnalysisMarkdown>
            {task.description || "No description yet."}
          </AnalysisMarkdown>
        )}
      </IssueComment>
      <IssueDiscussion
        resource="tasks"
        threadId={task.id}
        workspace={workspace}
        userId={userId}
        canEdit={canEdit}
      />
    </IssueDetail>
  );
}
