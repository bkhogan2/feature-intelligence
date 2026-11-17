import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  ActionList,
  ActionMenu,
  Button as PrimerButton,
  ButtonGroup,
} from "@primer/react";
import { TriangleDownIcon } from "@primer/octicons-react";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { api } from "@/lib/auth-context";
import { loadOpportunityPages } from "@/features/opportunities/opportunity-pagination";
import { TaskDraftReview } from "./task-draft-review";
import type { Task } from "./task-api";

type OpportunityOption = { id: string; name: string };

export function CreateTask({
  workspace,
  parent,
  boardHref,
  onCreated,
}: {
  workspace: string;
  parent?: OpportunityOption;
  boardHref?: string;
  onCreated: (task: Task) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draftOpen, setDraftOpen] = useState(false);
  const [options, setOptions] = useState<OpportunityOption[]>([]);
  const [opportunity, setOpportunity] = useState("");
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const submission = useRef<{
    id: string;
    title: string;
    parent: string;
  } | null>(null);
  const parentId = parent?.id;

  useEffect(() => {
    if (!open || parentId) return;
    const controller = new AbortController();
    setLoading(true);
    loadOpportunityPages<OpportunityOption>((offset) =>
      api(
        `/opportunities?limit=100&offset=${offset}`,
        { signal: controller.signal },
        workspace,
      ),
    )
      .then((items) => {
        if (!controller.signal.aborted) setOptions(items);
      })
      .catch((err: Error) => {
        if (!controller.signal.aborted) setError(err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [open, parentId, workspace]);

  async function submit() {
    const opportunityId = parentId ?? opportunity;
    const value = title.trim();
    if (!value || !opportunityId || saving) return;
    setSaving(true);
    setError("");
    if (
      submission.current?.title !== value ||
      submission.current.parent !== opportunityId
    ) {
      submission.current = {
        id: crypto.randomUUID(),
        title: value,
        parent: opportunityId,
      };
    }
    try {
      const task = await api<Task>(
        "/tasks",
        {
          method: "POST",
          body: JSON.stringify({
            id: submission.current.id,
            title: value,
            opportunity_id: opportunityId,
          }),
        },
        workspace,
      );
      submission.current = null;
      setTitle("");
      setOpportunity("");
      setOpen(false);
      onCreated(task);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (saving) return;
          setError("");
          setOpen(next);
        }}
      >
        {boardHref ? (
          <ButtonGroup aria-label="Sub-issue actions">
            <DialogTrigger asChild>
              <PrimerButton size="small">Create sub-issue</PrimerButton>
            </DialogTrigger>
            <ActionMenu>
              <ActionMenu.Anchor>
                <PrimerButton
                  size="small"
                  aria-label="More sub-issue actions"
                  style={{ width: 28, paddingInline: 0 }}
                >
                  <TriangleDownIcon aria-hidden />
                </PrimerButton>
              </ActionMenu.Anchor>
              <ActionMenu.Overlay align="start">
                <ActionList>
                  {parent && (
                    <ActionList.Item onSelect={() => setDraftOpen(true)}>
                      Draft sub-issues with AI
                    </ActionList.Item>
                  )}
                  <ActionList.LinkItem href={boardHref}>
                    View sub-issues on board
                  </ActionList.LinkItem>
                </ActionList>
              </ActionMenu.Overlay>
            </ActionMenu>
          </ButtonGroup>
        ) : (
          <DialogTrigger asChild>
            <Button size="sm" variant="outline">
              Add task
            </Button>
          </DialogTrigger>
        )}
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {boardHref ? "Create sub-issue" : "Add task"}
            </DialogTitle>
            <DialogDescription>
              {parent
                ? `For ${parent.name}`
                : "Choose the opportunity this task belongs to."}
            </DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            {!parent && (
              <label className="block space-y-1 text-sm font-medium">
                <span>Opportunity</span>
                <select
                  required
                  value={opportunity}
                  disabled={loading || saving}
                  className="block w-full rounded-md border bg-background p-2"
                  onChange={(event) => setOpportunity(event.target.value)}
                >
                  <option value="">
                    {loading
                      ? "Loading opportunities…"
                      : options.length
                        ? "Choose an opportunity"
                        : "No active opportunities"}
                  </option>
                  {options.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="block space-y-1 text-sm font-medium">
              <span>Title</span>
              <Input
                required
                maxLength={160}
                value={title}
                disabled={saving}
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
            <DialogFooter>
              <Button
                type="submit"
                disabled={
                  saving ||
                  loading ||
                  !title.trim() ||
                  !(parentId || opportunity)
                }
              >
                {saving
                  ? "Creating…"
                  : boardHref
                    ? "Create sub-issue"
                    : "Add task"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      {parentId && boardHref && (
        <TaskDraftReview
          open={draftOpen}
          onOpenChange={setDraftOpen}
          workspace={workspace}
          opportunityId={parentId}
          onCreated={(tasks) => tasks.forEach(onCreated)}
        />
      )}
    </>
  );
}
