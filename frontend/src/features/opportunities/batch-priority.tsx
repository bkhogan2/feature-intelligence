import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";

type Priority = "high" | "medium" | "low";
type Result = {
  priority: Priority;
  impact?: Priority;
  confidence?: Priority;
  evidence?: { feedback_id: string; quote: string }[];
  rationale: string;
  missing_information: string[];
  workflow_impact: string;
  evidence_strength: string;
  dependencies: string;
  goals_alignment: string;
};
type BatchItem = {
  opportunity_id: string;
  name: string;
  current_priority: Priority | null;
  expected_revision: number;
  expected_evidence_revision: number;
  effort: string;
  dependencies: string;
  analysis: {
    id: string;
    status: string;
    error?: string;
    budget_ceiling_usd?: number;
    evidence_limit_per_opportunity?: number;
    evidence_description_limit?: number;
    result?: Result;
  };
};
type Batch = { id: string; status: string; items: BatchItem[] };
type Draft = { selected: boolean; priority: Priority; rationale: string };
export const MAX_PRIORITY_BATCH = 50;
export function batchScopeError(count: number) {
  return count === 0
    ? "No opportunities in this scope."
    : count > MAX_PRIORITY_BATCH
      ? `One comparative batch supports up to ${MAX_PRIORITY_BATCH} opportunities. Narrow your filters or selection; this scope contains ${count}.`
      : "";
}
export function BatchPriority({
  workspace,
  selectedIds,
  filteredIds,
  disabled,
  onRefresh,
  request = api,
}: {
  workspace: string;
  selectedIds: string[];
  filteredIds: string[];
  disabled: boolean;
  onRefresh: () => Promise<void>;
  request?: typeof api;
}) {
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<string[]>([]);
  const [scopeLabel, setScopeLabel] = useState("");
  const [batch, setBatch] = useState<Batch | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [stale, setStale] = useState(false);
  const [pollRevision, setPollRevision] = useState(0);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const pending = batch?.status === "running" || batch?.status === "queued";
  function receive(value: Batch) {
    setBatch(value);
    setDrafts((previous) => {
      const next = { ...previous };
      for (const item of value.items)
        if (item.analysis.result && !next[item.opportunity_id])
          next[item.opportunity_id] = {
            selected: true,
            priority: item.analysis.result.priority,
            rationale: item.analysis.result.rationale,
          };
      return next;
    });
  }
  useEffect(() => {
    if (!pending || !batch) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function poll() {
      try {
        const value = await request<Batch>(
          `/opportunities/priority/batches/${batch!.id}`,
          { signal: controller.signal },
          workspace,
        );
        if (cancelled) return;
        receive(value);
        setError("");
        if (value.status === "running" || value.status === "queued")
          timer = setTimeout(poll, 2000);
      } catch (err) {
        if (!cancelled)
          setError(
            `Could not check batch progress: ${(err as Error).message}. Retry checking; do not start a duplicate batch.`,
          );
      }
    }
    timer = setTimeout(poll, 1500);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [batch?.id, pending, workspace, pollRevision]);
  function choose(ids: string[], label: string) {
    setScope([...ids]);
    setScopeLabel(label);
    setBatch(null);
    setDrafts({});
    setError("");
    setNotice("");
    setStale(false);
    setOpen(true);
  }
  async function generate() {
    if (busy || pending || batchScopeError(scope.length)) return;
    setBusy(true);
    setError("");
    setStale(false);
    setDrafts({});
    setBatch(null);
    try {
      const value = await request<Batch>(
        "/opportunities/priority/batch-assess",
        { method: "POST", body: JSON.stringify({ opportunity_ids: scope }) },
        workspace,
      );
      if (alive.current) receive(value);
    } catch (err) {
      if (alive.current) setError((err as Error).message);
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  async function save() {
    if (!batch || busy || pending || stale) return;
    const chosen = batch.items.filter(
      (item) => drafts[item.opportunity_id]?.selected,
    );
    if (!chosen.length) return;
    setBusy(true);
    setError("");
    try {
      await request(
        "/opportunities/priority/batch",
        {
          method: "PUT",
          body: JSON.stringify({
            items: chosen.map((item) => {
              const draft = drafts[item.opportunity_id];
              const unchanged =
                draft.priority === item.analysis.result?.priority &&
                draft.rationale === item.analysis.result?.rationale;
              return {
                opportunity_id: item.opportunity_id,
                priority: draft.priority,
                rationale: draft.rationale,
                effort: item.effort,
                dependencies: item.dependencies,
                expected_revision: item.expected_revision,
                expected_evidence_revision: item.expected_evidence_revision,
                accepted_analysis_id: unchanged ? item.analysis.id : null,
              };
            }),
          }),
        },
        workspace,
      );
      if (!alive.current) return;
      setNotice(`Saved priorities for ${chosen.length} opportunities.`);
      setBatch(null);
      setDrafts({});
      setOpen(false);
      try {
        await onRefresh();
      } catch (err) {
        setError(
          `Priorities were saved, but refreshing the list failed: ${(err as Error).message}`,
        );
      }
    } catch (err) {
      if (!alive.current) return;
      if (err instanceof Error && "status" in err && err.status === 409)
        setStale(true);
      setError((err as Error).message);
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  const chosenCount = Object.values(drafts).filter(
    (draft) => draft.selected,
  ).length;
  const invalid = Object.values(drafts).some(
    (draft) => draft.selected && !draft.rationale.trim(),
  );
  return (
    <>
      <div
        className="flex flex-wrap items-center gap-2"
        aria-label="AI batch priority actions"
      >
        <Button
          size="sm"
          variant="outline"
          disabled={disabled || busy || !!batch || !selectedIds.length}
          onClick={() => choose(selectedIds, "Selected opportunities")}
        >
          AI prioritize selected ({selectedIds.length})
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={disabled || busy || !!batch || !filteredIds.length}
          onClick={() =>
            choose(filteredIds, "All filtered opportunities, across every page")
          }
        >
          AI prioritize all filtered ({filteredIds.length})
        </Button>
        {(batch || busy) && (
          <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>
            {pending || busy ? "View pending AI batch" : "Review AI batch"}
          </Button>
        )}
      </div>
      {notice && (
        <p role="status" className="text-sm">
          {notice}
        </p>
      )}
      {!open && error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <Dialog
        open={open}
        onOpenChange={(value) => {
          if (!busy) setOpen(value);
        }}
      >
        <DialogContent className="sm:max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Compare and prioritize opportunities</DialogTitle>
            <DialogDescription>
              {scopeLabel}: {scope.length} opportunities. The AI evaluates this
              entire scope together. Priorities change only when you save your
              reviewed choices. Generation is bounded by the server cost limit;
              a large batch may need narrower filters.
            </DialogDescription>
          </DialogHeader>
          {batchScopeError(scope.length) && (
            <p role="alert">{batchScopeError(scope.length)}</p>
          )}
          {!batch && (
            <Button
              disabled={disabled || busy || !!batchScopeError(scope.length)}
              onClick={generate}
            >
              {busy
                ? "Starting comparative assessment…"
                : "Generate suggestions"}
            </Button>
          )}
          {pending && (
            <p role="status">
              Comparing {scope.length} opportunities… You can close this review
              and reopen it here. Closing does not cancel server generation or
              save priorities.
            </p>
          )}
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          {pending && error && (
            <Button
              variant="outline"
              onClick={() => setPollRevision((value) => value + 1)}
            >
              Retry checking progress
            </Button>
          )}
          {batch?.status === "failed" && (
            <p role="alert">
              This assessment failed. No priorities were saved. Retry the same
              scope below.
            </p>
          )}
          {stale && (
            <p role="alert">
              An opportunity or its evidence changed. No changes were saved.
              Generate fresh suggestions before saving.
            </p>
          )}
          {batch?.items[0]?.analysis.budget_ceiling_usd !== undefined && (
            <p className="text-xs text-muted-foreground">
              Server cost ceiling: ${batch.items[0].analysis.budget_ceiling_usd}
              . Evidence reviewed: at most{" "}
              {batch.items[0].analysis.evidence_limit_per_opportunity} linked
              requests per opportunity,{" "}
              {batch.items[0].analysis.evidence_description_limit} characters
              each.
            </p>
          )}
          {batch && !pending && (
            <>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy}
                  onClick={() =>
                    setDrafts((values) =>
                      Object.fromEntries(
                        Object.entries(values).map(([id, value]) => [
                          id,
                          { ...value, selected: true },
                        ]),
                      ),
                    )
                  }
                >
                  Select all suggestions
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() =>
                    setDrafts((values) =>
                      Object.fromEntries(
                        Object.entries(values).map(([id, value]) => [
                          id,
                          { ...value, selected: false },
                        ]),
                      ),
                    )
                  }
                >
                  Clear choices
                </Button>
              </div>
              {batch.items.map((item) => {
                const result = item.analysis.result;
                const draft = drafts[item.opportunity_id];
                return (
                  <article
                    key={item.opportunity_id}
                    className="space-y-3 rounded-lg border p-4"
                  >
                    <h3 className="font-semibold">{item.name}</h3>
                    <p className="text-sm capitalize">
                      Current: {item.current_priority || "unprioritized"} →
                      Suggested: {result?.priority || "unavailable"}
                    </p>
                    {result && draft ? (
                      <fieldset
                        disabled={busy || disabled}
                        className="space-y-3"
                      >
                        <label className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={draft.selected}
                            onChange={(e) =>
                              setDrafts((values) => ({
                                ...values,
                                [item.opportunity_id]: {
                                  ...draft,
                                  selected: e.target.checked,
                                },
                              }))
                            }
                          />
                          Apply priority for {item.name}
                        </label>
                        <p className="text-sm">{result.rationale}</p>
                        <p className="text-sm capitalize">
                          Impact: {result.impact || "not assessed"} ·
                          Confidence: {result.confidence || "not assessed"}
                        </p>
                        {result.evidence?.map((cite, index) => (
                          <blockquote
                            key={index}
                            className="border-l-2 pl-3 text-sm"
                          >
                            <p>“{cite.quote}”</p>
                            <a
                              className="underline"
                              target="_blank"
                              rel="noreferrer"
                              href={`#inbox?status=all&id=${encodeURIComponent(cite.feedback_id)}`}
                            >
                              Open linked feedback
                            </a>
                          </blockquote>
                        ))}
                        <p className="text-sm">
                          <strong>Evidence:</strong> {result.evidence_strength}
                        </p>
                        <p className="text-sm">
                          <strong>Workflow impact:</strong>{" "}
                          {result.workflow_impact}
                        </p>
                        <p className="text-sm">
                          <strong>Goals:</strong> {result.goals_alignment}
                        </p>
                        <p className="text-sm">
                          <strong>Dependencies:</strong> {result.dependencies}
                        </p>
                        <div className="text-sm">
                          <strong>Missing information</strong>
                          {result.missing_information.length ? (
                            <ul className="list-disc pl-5">
                              {result.missing_information.map((gap, i) => (
                                <li key={i}>{gap}</li>
                              ))}
                            </ul>
                          ) : (
                            <p>No gaps reported by AI.</p>
                          )}
                        </div>
                        <label className="block text-sm">
                          Priority to save
                          <select
                            className="ml-3 rounded border bg-background p-2"
                            value={draft.priority}
                            onChange={(e) =>
                              setDrafts((values) => ({
                                ...values,
                                [item.opportunity_id]: {
                                  ...draft,
                                  priority: e.target.value as Priority,
                                },
                              }))
                            }
                          >
                            {["high", "medium", "low"].map((priority) => (
                              <option key={priority}>{priority}</option>
                            ))}
                          </select>
                        </label>
                        <label className="block text-sm">
                          Rationale to save
                          <textarea
                            className="mt-2 block w-full rounded border bg-background p-2"
                            rows={3}
                            maxLength={2000}
                            value={draft.rationale}
                            onChange={(e) =>
                              setDrafts((values) => ({
                                ...values,
                                [item.opportunity_id]: {
                                  ...draft,
                                  rationale: e.target.value,
                                },
                              }))
                            }
                          />
                        </label>
                      </fieldset>
                    ) : (
                      <p role="alert">
                        {item.analysis.error || "No suggestion available."}
                      </p>
                    )}
                  </article>
                );
              })}
              <Button
                disabled={
                  disabled ||
                  busy ||
                  stale ||
                  !chosenCount ||
                  invalid ||
                  batch.status !== "complete"
                }
                onClick={save}
              >
                {busy
                  ? "Saving reviewed priorities…"
                  : `Save ${chosenCount} reviewed ${chosenCount === 1 ? "priority" : "priorities"}`}
              </Button>
              {(stale || batch.status === "failed") && (
                <Button
                  variant="outline"
                  disabled={disabled || busy}
                  onClick={generate}
                >
                  Generate fresh suggestions
                </Button>
              )}
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => {
                  setBatch(null);
                  setDrafts({});
                  setOpen(false);
                  setError("");
                }}
              >
                Discard suggestions
              </Button>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
