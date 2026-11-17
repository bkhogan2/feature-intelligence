import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { api } from "@/lib/auth-context";
import type { Task } from "./task-api";

type Suggestion = { title: string; description: string };
type Draft = Suggestion & { id: string; selected: boolean };

export function TaskDraftReview({
  open,
  onOpenChange,
  workspace,
  opportunityId,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspace: string;
  opportunityId: string;
  onCreated: (tasks: Task[]) => void;
}) {
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [questions, setQuestions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const savePending = useRef(false);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const selected = drafts.filter((draft) => draft.selected);
  const endpoint = `/opportunities/${opportunityId}/tasks`;

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setDrafts([]);
    setQuestions([]);
    api<{ drafts: Suggestion[]; questions: string[] }>(
      `${endpoint}/draft`,
      { method: "POST", signal: controller.signal },
      workspace,
    )
      .then((result) => {
        if (controller.signal.aborted) return;
        setDrafts(
          result.drafts.map((draft) => ({
            ...draft,
            id: crypto.randomUUID(),
            selected: true,
          })),
        );
        setQuestions(result.questions);
      })
      .catch((err: Error) => {
        if (!controller.signal.aborted) setError(err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [open, attempt, endpoint, workspace]);

  function edit(id: string, changes: Partial<Omit<Draft, "id">>) {
    setDrafts((current) =>
      current.map((draft) =>
        draft.id === id ? { ...draft, ...changes } : draft,
      ),
    );
  }

  async function createSelected() {
    if (
      loading ||
      savePending.current ||
      !selected.length ||
      selected.some((draft) => !draft.title.trim())
    )
      return;
    savePending.current = true;
    setSaving(true);
    setError("");
    try {
      const result = await api<{ items: Task[] }>(
        `${endpoint}/batch`,
        {
          method: "POST",
          body: JSON.stringify({
            tasks: selected.map(({ id, title, description }) => ({
              id,
              title: title.trim(),
              description,
            })),
          }),
        },
        workspace,
      );
      onCreated(result.items);
      onOpenChange(false);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      savePending.current = false;
      setSaving(false);
    }
  }

  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        if (!savePending.current) onOpenChange(next);
      }}
    >
      <SheetContent
        side="right"
        className="w-full overflow-y-auto sm:max-w-2xl"
      >
        <SheetHeader className="mb-5 pr-6">
          <SheetTitle>Draft sub-issues with AI</SheetTitle>
          <SheetDescription>
            Edit or deselect drafts. Selected sub-issues will be created in
            Backlog, unassigned.
          </SheetDescription>
        </SheetHeader>
        {loading && (
          <p role="status" className="text-sm text-muted-foreground">
            Drafting sub-issues…
          </p>
        )}
        {!loading && (
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              void createSelected();
            }}
          >
            {questions.length > 0 && (
              <section
                className="space-y-2 rounded-md border p-3 text-sm"
                aria-label="Clarifications"
              >
                <h3 className="font-medium">Needs clarification</h3>
                <ul className="list-disc space-y-1 pl-5">
                  {questions.map((question, index) => (
                    <li key={index}>{question}</li>
                  ))}
                </ul>
              </section>
            )}
            {!drafts.length && !error && (
              <p className="text-sm text-muted-foreground">
                No new sub-issues were suggested.
              </p>
            )}
            {drafts.map((draft, index) => (
              <fieldset
                key={draft.id}
                disabled={saving}
                className="space-y-3 rounded-md border p-3"
              >
                <label className="flex items-center gap-2 text-sm font-medium">
                  <Checkbox
                    checked={draft.selected}
                    onCheckedChange={(checked) =>
                      edit(draft.id, { selected: checked === true })
                    }
                  />
                  Include draft {index + 1}
                </label>
                <label className="block space-y-1 text-sm font-medium">
                  <span>Title</span>
                  <Input
                    value={draft.title}
                    maxLength={160}
                    onChange={(event) =>
                      edit(draft.id, { title: event.target.value })
                    }
                  />
                </label>
                <label className="block space-y-1 text-sm font-medium">
                  <span>Description</span>
                  <textarea
                    value={draft.description}
                    onChange={(event) =>
                      edit(draft.id, { description: event.target.value })
                    }
                    maxLength={20000}
                    rows={4}
                    className="block w-full rounded-md border bg-background p-2 font-normal"
                  />
                </label>
              </fieldset>
            ))}
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={saving}
                onClick={() => onOpenChange(false)}
              >
                Cancel
              </Button>
              {!drafts.length && error && (
                <Button
                  type="button"
                  onClick={() => setAttempt((value) => value + 1)}
                >
                  Try again
                </Button>
              )}
              {drafts.length > 0 && (
                <Button
                  type="submit"
                  disabled={
                    saving ||
                    !selected.length ||
                    selected.some((draft) => !draft.title.trim())
                  }
                >
                  {saving
                    ? "Creating…"
                    : `Create selected (${selected.length})`}
                </Button>
              )}
            </div>
          </form>
        )}
      </SheetContent>
    </Sheet>
  );
}
