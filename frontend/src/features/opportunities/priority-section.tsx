import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { createPortal } from "react-dom";
import { useEffect, useState } from "react";
import { api } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";

type Priority = "high" | "medium" | "low";
type ProductContext = { goals: string; stage: string; source: string };
type Assessment = {
  id: string;
  status: "queued" | "running" | "complete" | "failed";
  deadline_at: string;
  automatic?: boolean;
  model: string;
  prompt_version?: string;
  product_context?: ProductContext;
  alternative_count?: number;
  alternatives_truncated?: boolean;
  cost_usd?: number | null;
  completed_at?: string;
  error?: string;
  based_on_revision?: number;
  evidence_count?: number;
  result?: {
    impact?: Priority;
    confidence?: Priority;
    goals_alignment?: string;
    priority: Priority;
    rationale: string;
    workflow_impact: string;
    evidence_strength: string;
    dependencies: string;
    missing_information: string[];
    evidence: { feedback_id: string; quote: string }[];
  };
};
export type PriorityFields = {
  id: string;
  can_edit: boolean;
  priority: Priority | null;
  priority_rationale: string;
  effort: string;
  dependencies: string;
  priority_revision: number;
  priority_updated_by: string | null;
  priority_updated_at: string | null;
  priority_analysis: Assessment | null;
  priority_context?: ProductContext;
};
export function PrioritySection({
  detail,
  workspace,
  onChange,
  assessmentTarget,
  onAssessment,
}: {
  detail: PriorityFields;
  workspace: string;
  onChange: (value: PriorityFields) => void;
  assessmentTarget: HTMLElement | null;
  onAssessment: (id: string, analysis: Assessment) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [priority, setPriority] = useState<Priority>(
    detail.priority || "medium",
  );
  const [rationale, setRationale] = useState(detail.priority_rationale);
  const [effort, setEffort] = useState(detail.effort);
  const [dependencies, setDependencies] = useState(detail.dependencies);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [assessmentError, setAssessmentError] = useState("");
  const [message, setMessage] = useState("");
  const analysis = detail.priority_analysis;
  const running =
    analysis?.status === "running" &&
    new Date(analysis.deadline_at).getTime() > Date.now();
  const queued = analysis?.status === "queued";
  const result = analysis?.status === "complete" ? analysis.result : undefined;
  const legacy =
    !!result &&
    (!result.impact ||
      !result.confidence ||
      analysis?.prompt_version !== "priority-v2");
  useEffect(() => {
    if (!running && !queued) return;
    let alive = true;
    const timer = window.setInterval(() => {
      api<PriorityFields>(`/opportunities/${detail.id}`, {}, workspace)
        .then((value) => {
          if (alive) onChange(value);
        })
        .catch((err: Error) => {
          if (alive) setError(err.message);
        });
    }, 2000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [running, queued, detail.id, workspace, onChange]);
  async function assess() {
    setBusy(true);
    setAssessmentError("");
    setMessage("");
    try {
      const run = await api<Assessment>(
        `/opportunities/${detail.id}/priority/assess`,
        { method: "POST" },
        workspace,
      );
      onAssessment(detail.id, run);
    } catch (err) {
      setAssessmentError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function save(accept: boolean) {
    if (accept && !result) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const updated = await api<PriorityFields>(
        `/opportunities/${detail.id}/priority`,
        {
          method: "PUT",
          body: JSON.stringify({
            priority: accept ? result!.priority : priority,
            rationale: accept ? result!.rationale : rationale,
            effort: accept ? detail.effort : effort,
            dependencies: accept ? detail.dependencies : dependencies,
            expected_revision: detail.priority_revision,
            accepted_analysis_id: accept ? analysis!.id : null,
          }),
        },
        workspace,
      );
      onChange(updated);
      setEditing(false);
      setMessage("Priority saved. Lifecycle status unchanged.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function edit() {
    setPriority(detail.priority || result?.priority || "medium");
    setRationale(detail.priority_rationale || result?.rationale || "");
    setEffort(detail.effort);
    setDependencies(detail.dependencies);
    setEditing(true);
    setMessage("");
  }
  const review = (
    <section className="space-y-4" aria-label="Opportunity priority">
      <div>
        <p className="mt-2 font-medium capitalize">
          {detail.priority
            ? `${detail.priority} · PM confirmed`
            : "Not yet prioritized"}
        </p>
        <p className="mt-1 whitespace-pre-wrap text-sm">
          {detail.priority_rationale ||
            "Set relative attention after reviewing workflow impact, evidence and effort."}
        </p>
        {detail.priority_updated_at && (
          <p className="mt-2 break-all text-xs text-muted-foreground">
            {detail.priority_updated_by} ·{" "}
            {new Date(detail.priority_updated_at).toLocaleString()}
          </p>
        )}
      </div>
      {detail.priority_context && (
        <section
          aria-label="Product goals context"
          className="space-y-2 rounded-lg bg-muted/50 p-4 text-sm"
        >
          <h4 className="font-medium">Product goals context</h4>
          <p>{detail.priority_context.goals}</p>
          <p className="text-muted-foreground">
            {detail.priority_context.stage}
          </p>
          <p className="text-xs text-muted-foreground">
            {detail.priority_context.source}. Applies to this server; workspace
            editing is not available.
          </p>
        </section>
      )}
      <p className="text-sm text-muted-foreground">
        Potential impact describes workflow benefit. Confidence describes
        evidence strength. Priority weighs goals, alternatives, effort and
        dependencies. Missing evidence or zero votes alone do not determine
        priority.
      </p>
      <dl className="space-y-2 text-sm">
        <div>
          <dt className="font-medium">PM effort estimate</dt>
          <dd className="whitespace-pre-wrap text-muted-foreground">
            {detail.effort || "Unknown — needs a PM estimate"}
          </dd>
        </div>
        <div>
          <dt className="font-medium">PM dependencies</dt>
          <dd className="whitespace-pre-wrap text-muted-foreground">
            {detail.dependencies || "Not yet assessed"}
          </dd>
        </div>
      </dl>
      {result && (
        <div className="space-y-3 border-t pt-4">
          <h4 className="font-medium">AI assessment · human review required</h4>
          {legacy && (
            <p role="status" className="rounded-md border p-3 text-sm">
              Earlier assessment: impact and confidence were not separately
              rated and current product goals may not have been considered.
              Reassess before accepting; the saved rationale remains available
              below.
            </p>
          )}
          <dl className="flex flex-wrap gap-x-8 gap-y-3 text-sm">
            <div>
              <dt className="text-muted-foreground">Potential impact</dt>
              <dd className="font-semibold capitalize">
                {result.impact || "Not separately assessed"}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Confidence</dt>
              <dd className="font-semibold capitalize">
                {result.confidence || "Not separately assessed"}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Suggested priority</dt>
              <dd className="font-semibold capitalize">{result.priority}</dd>
            </div>
          </dl>
          <p className="text-sm">{result.rationale}</p>
          <dl className="space-y-2 text-sm">
            {[
              ["Potential workflow impact", result.workflow_impact],
              ["Confidence and evidence", result.evidence_strength],
              ...(result.goals_alignment
                ? [["Goals and tradeoffs", result.goals_alignment]]
                : []),
              ["Dependencies to check", result.dependencies],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="font-medium">{label}</dt>
                <dd className="text-muted-foreground">{value}</dd>
              </div>
            ))}
          </dl>
          {result.evidence.length > 0 && (
            <ul className="space-y-2 text-sm">
              {result.evidence.map((cite, index) => (
                <li key={`${cite.feedback_id}-${index}`}>
                  <a
                    className="underline underline-offset-2"
                    href={`#inbox?status=all&id=${cite.feedback_id}`}
                  >
                    “{cite.quote}”
                  </a>
                </li>
              ))}
            </ul>
          )}
          <div className="text-sm">
            <h5 className="font-medium">Missing information</h5>
            {result.missing_information.length ? (
              <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                {result.missing_information.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            ) : (
              <p className="text-muted-foreground">
                No additional gaps identified by this assessment.
              </p>
            )}
          </div>
          {analysis!.product_context &&
            detail.priority_context &&
            (analysis!.product_context.goals !==
              detail.priority_context.goals ||
              analysis!.product_context.stage !==
                detail.priority_context.stage) && (
              <details className="text-sm">
                <summary>
                  Goals used for this saved assessment differ from the current
                  configuration
                </summary>
                <p className="mt-2">{analysis!.product_context.goals}</p>
                <p>{analysis!.product_context.stage}</p>
              </details>
            )}
          <p className="text-xs text-muted-foreground">
            {analysis!.model} ·{" "}
            {analysis!.prompt_version || "Earlier assessment"} ·{" "}
            {analysis!.completed_at &&
              new Date(analysis!.completed_at).toLocaleString()}{" "}
            · Based on {analysis!.evidence_count ?? "linked"} request(s). Human
            review required; priority does not commit implementation.
            {analysis!.alternative_count !== undefined &&
              ` Compared ${analysis!.alternative_count} other opportunity summaries${analysis!.alternatives_truncated ? " (bounded set)" : ""}.`}
            {analysis!.cost_usd != null &&
              ` Model-reported cost: $${analysis!.cost_usd.toFixed(6)}.`}
          </p>
        </div>
      )}
      {analysis?.status === "failed" && (
        <p role="status" className="text-sm text-muted-foreground">
          {analysis.error}
        </p>
      )}
      {analysis?.status === "running" && !running && (
        <p role="status" className="text-sm">
          Assessment expired or was interrupted. Retry when ready.
        </p>
      )}
      {running && (
        <p role="status" className="text-sm">
          Assessing linked evidence… You can leave this opportunity and return.
        </p>
      )}
      {queued && (
        <p role="status" className="rounded border p-3 text-sm">
          Priority assessment queued after PM approval.{" "}
          {analysis?.error ||
            "Waiting for configured capacity and shared automatic allocation."}{" "}
          Confirmed priority and lifecycle are unchanged.
        </p>
      )}
      {analysis?.automatic && (
        <p className="text-xs text-muted-foreground">
          Automatic suggestion after PM grouping approval. Accept or edit
          priority separately; this does not plan implementation.
        </p>
      )}
      {detail.can_edit && (
        <div className="flex flex-wrap gap-2">
          {result && (
            <Button
              disabled={busy || running || editing || legacy}
              onClick={() => void save(true)}
            >
              Accept priority
            </Button>
          )}
          <Button variant="outline" disabled={busy || editing} onClick={edit}>
            {detail.priority || result
              ? "Edit priority"
              : "Set priority manually"}
          </Button>
        </div>
      )}
      {editing && (
        <form
          className="space-y-3 border-t pt-4"
          onSubmit={(event) => {
            event.preventDefault();
            void save(false);
          }}
        >
          <label className="block text-sm font-medium">
            Priority
            <select
              aria-label="Priority"
              className="mt-1 block w-full rounded-md border bg-background p-2"
              value={priority}
              onChange={(e) => setPriority(e.target.value as Priority)}
            >
              {["high", "medium", "low"].map((value) => (
                <option key={value} value={value}>
                  {value[0].toUpperCase() + value.slice(1)}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm font-medium">
            Priority rationale
            <textarea
              required
              maxLength={2000}
              rows={3}
              className="mt-1 block w-full rounded-md border bg-background p-2 font-normal"
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
            />
          </label>
          <label className="block text-sm font-medium">
            PM effort estimate
            <textarea
              maxLength={1000}
              rows={2}
              placeholder="Leave blank if unknown"
              className="mt-1 block w-full rounded-md border bg-background p-2 font-normal"
              value={effort}
              onChange={(e) => setEffort(e.target.value)}
            />
          </label>
          <label className="block text-sm font-medium">
            Dependencies
            <textarea
              maxLength={1000}
              rows={2}
              className="mt-1 block w-full rounded-md border bg-background p-2 font-normal"
              value={dependencies}
              onChange={(e) => setDependencies(e.target.value)}
            />
          </label>
          <div className="flex gap-2">
            <Button disabled={busy || !rationale.trim()} type="submit">
              Save priority
            </Button>
            <Button
              disabled={busy}
              variant="ghost"
              type="button"
              onClick={() => setEditing(false)}
            >
              Cancel
            </Button>
          </div>
        </form>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="text-sm">
          {message}
        </p>
      )}
    </section>
  );
  return (
    <Sheet>
      {assessmentTarget &&
        createPortal(
          <div className="flex flex-col items-start gap-2">
            {detail.can_edit && (
              <Button
                size="sm"
                variant="outline"
                disabled={busy || running || queued || editing}
                onClick={() => void assess()}
              >
                {queued
                  ? "Priority assessment queued"
                  : running
                    ? "Assessing priority…"
                    : result
                      ? "Reassess priority"
                      : analysis?.status === "failed"
                        ? "Retry priority assessment"
                        : "Assess priority with AI"}
              </Button>
            )}
            {assessmentError && (
              <p role="alert" className="text-sm text-destructive">
                {assessmentError}
              </p>
            )}
            <SheetTrigger asChild>
              <Button size="sm" variant="outline">
                Review priority
              </Button>
            </SheetTrigger>
          </div>,
          assessmentTarget,
        )}
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
        <SheetHeader className="mb-6 pr-6">
          <SheetTitle>Review priority</SheetTitle>
          <SheetDescription>
            Review evidence, effort, and the suggested priority.
          </SheetDescription>
        </SheetHeader>
        {review}
      </SheetContent>
    </Sheet>
  );
}
