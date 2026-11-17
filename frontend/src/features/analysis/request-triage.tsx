import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Button as PrimerButton, Link as PrimerLink } from "@primer/react";
import { CrossReferenceIcon, CheckIcon } from "@primer/octicons-react";
import { Sparkles } from "lucide-react";
import { api } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ReviewerCorrection, type Correction } from "./reviewer-correction";
import { AnalysisMarkdown } from "./analysis-markdown";
type Result = {
  rationale_markdown: string;
  evidence: { feedback_id: string; quote: string }[];
} & (
  | { outcome: "existing_opportunity"; opportunity_id: string }
  | {
      outcome: "new_opportunity";
      proposed_name: string;
      proposed_problem: string;
    }
  | { outcome: "insufficient_context"; ambiguity: string; questions: string[] }
);
type Run = {
  id: string;
  status: "queued" | "running" | "complete" | "failed";
  automatic?: boolean;
  cost_usd?: number | string | null;
  model: string;
  prompt_version: string;
  created_at: string;
  completed_at: string | null;
  result: Result | null;
  error: string | null;
};
type Opportunity = {
  id: string;
  name: string;
  problem: string;
  original_suggestion?: Result;
  linked_by?: string;
  linked_at?: string;
  confirmation?: {
    choice: Correction;
    target: { name: string; problem: string };
  } | null;
};
export type TriageState = {
  run: Run | null;
  linked_opportunity: Opportunity | null;
};
type Config = {
  enabled: boolean;
  can_analyze: boolean;
  model: string;
  max_budget_usd: number;
  automatic?: { enabled: boolean };
};
const labels = {
  existing_opportunity: "Matches an existing opportunity",
  new_opportunity: "Suggests a new opportunity",
  insufficient_context: "Needs more context",
};
export function RequestTriage({
  requestId,
  workspace,
  onConfirmed,
  reviewOnly = false,
  approvalTarget,
  opportunityTarget,
  approvalAllowed = true,
}: {
  requestId: string;
  workspace: string;
  onConfirmed?: () => void;
  /** Show saved suggestions and approval controls without starting analysis. */
  reviewOnly?: boolean;
  approvalTarget?: HTMLElement | null;
  opportunityTarget?: HTMLElement | null;
  approvalAllowed?: boolean;
}) {
  const [state, setState] = useState<TriageState | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [matched, setMatched] = useState<Opportunity | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [revision, setRevision] = useState(0);
  const [notice, setNotice] = useState("");
  const [confirmedOpportunityId, setConfirmedOpportunityId] = useState<
    string | null
  >(null);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function load() {
      try {
        const [next, policy] = await Promise.all([
          api<TriageState>(
            `/feedback/${requestId}/triage`,
            { signal: controller.signal },
            workspace,
          ),
          api<Config>(
            "/triage/config",
            { signal: controller.signal },
            workspace,
          ),
        ]);
        if (controller.signal.aborted) return;
        setState(next);
        setConfig(policy);
        setError("");
        const result = next.run?.result;
        if (result?.outcome === "existing_opportunity") {
          const match = await api<Opportunity>(
            `/opportunities/${result.opportunity_id}`,
            { signal: controller.signal },
            workspace,
          );
          if (!controller.signal.aborted) setMatched(match);
        } else setMatched(null);
        if (next.run?.status === "running" || next.run?.status === "queued")
          timer = setTimeout(() => void load(), 2000);
      } catch (err) {
        if (!controller.signal.aborted) setError((err as Error).message);
      }
    }
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [workspace, requestId, revision]);
  async function act(
    confirm: boolean,
    choice: Correction = { mode: "accept" },
  ) {
    if (pending) return;
    setPending(true);
    setError("");
    setNotice("");
    try {
      if (confirm && state?.run) {
        const linked = await api<{ opportunity_id: string }>(
          `/feedback/${requestId}/triage/${state.run.id}/confirm`,
          { method: "POST", body: JSON.stringify(choice) },
          workspace,
        );
        setConfirmedOpportunityId(linked.opportunity_id);
        setNotice("Opportunity linked and request moved to Triaged.");
        onConfirmed?.();
      } else {
        const run = await api<Run>(
          `/feedback/${requestId}/triage`,
          { method: "POST" },
          workspace,
        );
        setState((current) => ({
          run,
          linked_opportunity: current?.linked_opportunity ?? null,
        }));
      }
      setRevision((v) => v + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  }
  const run = state?.run;
  const result = run?.status === "complete" ? run.result : null;
  const ready =
    !!result &&
    result.outcome !== "insufficient_context" &&
    !state?.linked_opportunity &&
    !!config?.can_analyze &&
    !error &&
    approvalAllowed;
  const linked = state?.linked_opportunity;
  return (
    <>
      {approvalTarget &&
        createPortal(
          <PrimerButton
            variant="primary"
            size="small"
            leadingVisual={CheckIcon}
            disabled={pending || !ready}
            title={
              !ready
                ? "A saved, reviewable opportunity suggestion is required for approval"
                : undefined
            }
            onClick={() => void act(true)}
          >
            {pending ? "Approving…" : linked ? "Approved" : "Approve"}
          </PrimerButton>,
          approvalTarget,
        )}
      {opportunityTarget &&
        createPortal(
          linked ? (
            <div className="issue-opportunity-link">
              <CrossReferenceIcon />
              <PrimerLink href={`#opportunities?id=${linked.id}`}>
                {linked.name}
              </PrimerLink>
            </div>
          ) : (
            <p>{state ? "No opportunity linked." : "Loading opportunity…"}</p>
          ),
          opportunityTarget,
        )}
      <section className="space-y-5" aria-label="Triage review">
        {!reviewOnly && (
          <div className="flex flex-wrap items-center gap-2">
            <Sparkles aria-hidden className="size-4" />
            <h3 className="text-sm font-semibold">AI triage</h3>
            <Badge variant="outline" className="ml-auto">
              {run?.status === "queued"
                ? "Queued"
                : run?.status === "running"
                  ? "Analyzing"
                  : run?.status === "complete"
                    ? "Ready for review"
                    : run?.status === "failed"
                      ? "Failed"
                      : "Not analyzed"}
            </Badge>
          </div>
        )}
        {!reviewOnly && (
          <>
            <p className="text-xs leading-relaxed text-muted-foreground">
              Analyze the underlying problem and suggest an opportunity or a
              focused clarification. Suggestions do not change feedback or
              lifecycle.
            </p>
            {config && !config.enabled && (
              <p className="text-sm text-muted-foreground">
                AI triage is not configured. A server-side Anthropic key and
                triage enablement are required.
              </p>
            )}
            {config && !config.can_analyze && (
              <p className="text-xs text-muted-foreground">
                An admin or editor can analyze and confirm requests. You can
                read saved results.
              </p>
            )}
            <div className="flex flex-wrap items-center gap-3">
              <Button
                size="sm"
                disabled={
                  pending ||
                  !config?.enabled ||
                  !config.can_analyze ||
                  run?.status === "running" ||
                  run?.status === "queued"
                }
                onClick={() => void act(false)}
              >
                <Sparkles aria-hidden className="size-4" />
                {run?.status === "queued"
                  ? "Queued for automatic triage"
                  : run?.status === "running"
                    ? "Analyzing…"
                    : pending
                      ? "Saving…"
                      : run?.status === "failed"
                        ? "Retry analysis"
                        : run?.status === "complete"
                          ? "Analyze again"
                          : "Analyze request"}
              </Button>
              {config && (
                <span className="text-xs text-muted-foreground">
                  {config.model} · ${config.max_budget_usd.toFixed(2)} run
                  budget
                </span>
              )}
            </div>
          </>
        )}
        {!reviewOnly && run?.status === "queued" && (
          <p role="status" className="text-sm text-muted-foreground">
            {!config?.automatic?.enabled
              ? "Automatic triage is paused. An editor can enable it on the capture page to resume queued work."
              : run.error ||
                "Queued durably for automatic triage. Waiting for configured worker capacity. No opportunity is created or linked without PM review."}
          </p>
        )}
        {!reviewOnly && run?.automatic && (
          <p className="text-xs text-muted-foreground">
            Submitted through workspace opt-in automation.{" "}
            {run.cost_usd != null &&
              `Model-reported cost: $${Number(run.cost_usd).toFixed(6)}.`}
          </p>
        )}
        {!reviewOnly && run?.status === "running" && (
          <p role="status" className="text-sm text-muted-foreground">
            Analysis is running on the server. You can leave this request and
            come back.
          </p>
        )}
        {!reviewOnly && run?.status === "failed" && (
          <p role="alert" className="text-sm text-destructive">
            {run.error || "Analysis failed. No opportunity was changed."}
          </p>
        )}
        {error && (
          <div role="alert" className="space-y-2">
            <p className="text-sm text-destructive">{error}</p>
            {!reviewOnly && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setRevision((v) => v + 1)}
              >
                Refresh analysis status
              </Button>
            )}
          </div>
        )}
        {result && (
          <div className="space-y-5 rounded-lg border p-5">
            <div>
              <p className="text-xs uppercase tracking-wider text-muted-foreground">
                AI suggestion · human review required
              </p>
              <h4 className="mt-2 font-semibold">{labels[result.outcome]}</h4>
            </div>
            {result.outcome === "existing_opportunity" && (
              <div>
                <h5 className="text-sm font-medium">
                  {matched?.name ?? "Workspace opportunity"}
                </h5>
                {matched && (
                  <p className="mt-1 whitespace-pre-wrap text-sm">
                    {matched.problem}
                  </p>
                )}
                <p className="mt-2 break-all font-mono text-xs text-muted-foreground">
                  {result.opportunity_id}
                </p>
              </div>
            )}
            {result.outcome === "new_opportunity" && (
              <div>
                <h5 className="text-sm font-medium">{result.proposed_name}</h5>
                <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-relaxed">
                  {result.proposed_problem}
                </p>
              </div>
            )}
            {result.outcome === "insufficient_context" && (
              <div className="space-y-3">
                <p className="text-sm">{result.ambiguity}</p>
                <ol className="list-decimal space-y-2 pl-5 text-sm">
                  {result.questions.map((q, i) => (
                    <li key={i}>{q}</li>
                  ))}
                </ol>
                <p className="text-xs text-muted-foreground">
                  Suggested questions only; nothing has been sent. A
                  clarification collection workflow is not connected yet.
                </p>
              </div>
            )}
            <AnalysisMarkdown>{result.rationale_markdown}</AnalysisMarkdown>
            <div className="space-y-3">
              <h5 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Quoted feedback evidence
              </h5>
              {result.evidence.map((e, i) => (
                <figure key={i} className="border-l-2 pl-3">
                  <blockquote className="whitespace-pre-wrap break-words text-sm">
                    {e.quote}
                  </blockquote>
                  <figcaption className="mt-1 break-all text-xs text-muted-foreground">
                    {e.feedback_id === requestId
                      ? "This request"
                      : `Related request ${e.feedback_id}`}
                  </figcaption>
                </figure>
              ))}
            </div>
            {run && (
              <p className="text-xs text-muted-foreground">
                {run.model} · {run.prompt_version} ·{" "}
                <time dateTime={run.completed_at ?? run.created_at}>
                  {new Date(
                    run.completed_at ?? run.created_at,
                  ).toLocaleString()}
                </time>
              </p>
            )}
          </div>
        )}
        {(!opportunityTarget || (!!result && !linked)) && (
          <section className="space-y-3 border-t pt-4" aria-label="PM decision">
            <h4 className="text-sm font-medium">PM decision</h4>
            {state?.linked_opportunity ? (
              <div className="text-sm">
                <p className="font-medium">
                  Linked to {state.linked_opportunity.name}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  PM approval recorded. This request is triaged; opportunity
                  status is managed separately.
                </p>
                {state.linked_opportunity.original_suggestion && (
                  <details className="mt-3 rounded border p-3">
                    <summary className="cursor-pointer text-sm font-medium">
                      Original AI suggestion at confirmation
                    </summary>
                    <p className="mt-3 text-sm">
                      {
                        labels[
                          state.linked_opportunity.original_suggestion.outcome
                        ]
                      }
                    </p>
                    <AnalysisMarkdown>
                      {
                        state.linked_opportunity.original_suggestion
                          .rationale_markdown
                      }
                    </AnalysisMarkdown>
                  </details>
                )}
                {state.linked_opportunity.confirmation && (
                  <div
                    className="mt-3 space-y-2 rounded border p-3"
                    aria-label="Recorded reviewer decision"
                  >
                    <p className="font-medium">
                      {state.linked_opportunity.confirmation.choice.mode ===
                      "accept"
                        ? "Original AI suggestion accepted"
                        : "Human correction recorded"}
                    </p>
                    <p>{state.linked_opportunity.confirmation.target.name}</p>
                    <p className="whitespace-pre-wrap">
                      {state.linked_opportunity.confirmation.target.problem}
                    </p>
                    {state.linked_opportunity.confirmation.choice.reason && (
                      <p>
                        Reason:{" "}
                        {state.linked_opportunity.confirmation.choice.reason}
                      </p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      {state.linked_opportunity.linked_by} ·{" "}
                      {state.linked_opportunity.linked_at &&
                        new Date(
                          state.linked_opportunity.linked_at,
                        ).toLocaleString()}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      The original AI run remains saved separately. This record
                      describes the confirmed human choice.
                    </p>
                  </div>
                )}
              </div>
            ) : result && result.outcome !== "insufficient_context" ? (
              <ReviewerCorrection
                key={`${workspace}:${requestId}:${run?.id}`}
                workspace={workspace}
                proposal={
                  result.outcome === "new_opportunity"
                    ? {
                        name: result.proposed_name,
                        problem: result.proposed_problem,
                      }
                    : null
                }
                pending={pending}
                disabled={!config?.can_analyze || !!error || !approvalAllowed}
                onConfirm={(choice) => void act(true, choice)}
              />
            ) : (
              <p className="text-xs text-muted-foreground">
                No opportunity is linked yet. A reviewer can approve a saved
                suggestion from this request or use the bulk triage review.
              </p>
            )}
            {notice && (
              <p role="status" className="text-sm">
                {notice}
                {confirmedOpportunityId && (
                  <>
                    {" "}
                    <a
                      className="font-medium underline underline-offset-2"
                      href={`#opportunities?id=${confirmedOpportunityId}`}
                    >
                      View opportunity
                    </a>
                  </>
                )}
              </p>
            )}
          </section>
        )}
      </section>
    </>
  );
}
