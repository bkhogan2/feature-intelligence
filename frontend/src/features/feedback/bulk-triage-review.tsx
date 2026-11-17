import { useEffect, useState } from "react";
import { api } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { AnalysisMarkdown } from "@/features/analysis/analysis-markdown";
import type { TriageState } from "@/features/analysis/request-triage";
import type { RequestItem } from "./request-table";

type Review = {
  request: RequestItem;
  state?: TriageState;
  target?: { name: string; problem: string };
  excluded?: string;
};
export function BulkTriageReview({
  workspace,
  requests,
  canEdit,
  onClose,
  onOpen,
  onConfirmed,
}: {
  workspace: string;
  requests: RequestItem[];
  canEdit: boolean;
  onClose: () => void;
  onOpen: (id: string) => void;
  onConfirmed: (ids: string[]) => void;
}) {
  const [rows, setRows] = useState<Review[]>([]);
  const [chosen, setChosen] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setChosen([]);
    void Promise.all(
      requests.map(async (request): Promise<Review> => {
        if (request.status === "triaged" || request.status === "archived")
          return {
            request,
            excluded:
              request.status === "triaged"
                ? "Already triaged"
                : "Archived; restore before review",
          };
        try {
          const state = await api<TriageState>(
            `/feedback/${request.id}/triage`,
            { signal: controller.signal },
            workspace,
          );
          const run = state.run;
          let excluded = state.linked_opportunity
            ? "Already linked to an opportunity"
            : !run
              ? "No saved analysis"
              : run.status !== "complete"
                ? `Analysis ${run.status}`
                : !run.result
                  ? "No saved suggestion"
                  : run.result.outcome === "insufficient_context"
                    ? "Needs more context; review individually"
                    : undefined;
          const result = run?.result;
          const target =
            !excluded && result?.outcome === "existing_opportunity"
              ? await api<{
                  name: string;
                  problem: string;
                  archived?: boolean;
                }>(
                  `/opportunities/${result.opportunity_id}`,
                  { signal: controller.signal },
                  workspace,
                )
              : undefined;
          if (target?.archived)
            excluded = "Suggested opportunity is archived; review individually";
          return { request, state, target, excluded };
        } catch (err) {
          return {
            request,
            excluded: `Could not load review: ${(err as Error).message}`,
          };
        }
      }),
    ).then((next) => {
      if (!controller.signal.aborted) {
        setRows(next);
        setLoading(false);
      }
    });
    return () => controller.abort();
  }, [requests, workspace, revision]);
  const eligible = rows.filter((row) => !row.excluded);
  const approved = eligible.filter((row) => chosen.includes(row.request.id));
  const newCount = approved.filter(
    (row) => row.state?.run?.result?.outcome === "new_opportunity",
  ).length;
  async function confirm() {
    if (!canEdit || pending || loading || !approved.length) return;
    setPending(true);
    setError("");
    try {
      await api(
        "/feedback/triage/confirm-batch",
        {
          method: "POST",
          body: JSON.stringify({
            items: approved.map((row) => ({
              feedback_id: row.request.id,
              run_id: row.state!.run!.id,
            })),
          }),
        },
        workspace,
      );
      onConfirmed(approved.map((row) => row.request.id));
      onClose();
    } catch (err) {
      setError(
        `Could not confirm: ${(err as Error).message}. Your review and selection are retained. Refresh suggestions to review any changes before retrying.`,
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open && !pending) onClose();
      }}
    >
      <SheetContent
        className="w-full overflow-y-auto sm:max-w-3xl"
        onEscapeKeyDown={(event) => {
          if (pending) event.preventDefault();
        }}
        onPointerDownOutside={(event) => {
          if (pending) event.preventDefault();
        }}
      >
        <SheetHeader>
          <SheetTitle>Review triage</SheetTitle>
          <SheetDescription>
            Review saved suggestions and choose which decisions to approve. No
            analysis is generated. Nothing changes until you confirm.
          </SheetDescription>
        </SheetHeader>
        <div className="mt-6 space-y-5">
          {loading ? (
            <p role="status">Loading saved suggestions…</p>
          ) : (
            <>
              <p className="text-sm">
                {eligible.length} eligible · {rows.length - eligible.length}{" "}
                excluded. Each new suggestion creates a separate opportunity.
                Open a request to correct a suggestion or link it to an existing
                opportunity.
              </p>
              {!eligible.length && (
                <p role="status">
                  No eligible suggestions to approve. Open individual requests
                  to resolve missing analysis or unclear context.
                </p>
              )}
              {rows.map(({ request, state, target, excluded }) => {
                const result = state?.run?.result;
                return (
                  <article
                    key={request.id}
                    className="space-y-3 rounded-lg border p-4"
                    aria-label={`Review ${request.title}`}
                  >
                    <h3 className="font-semibold">{request.title}</h3>
                    <p className="whitespace-pre-wrap text-sm">
                      {request.description}
                    </p>
                    {excluded ? (
                      <p className="text-sm text-muted-foreground">
                        Excluded: {excluded}
                      </p>
                    ) : (
                      <>
                        <label className="flex items-center gap-2 text-sm font-medium">
                          <input
                            type="checkbox"
                            checked={chosen.includes(request.id)}
                            disabled={pending || !canEdit}
                            onChange={(event) =>
                              setChosen((current) =>
                                event.target.checked
                                  ? [...current, request.id]
                                  : current.filter((id) => id !== request.id),
                              )
                            }
                          />
                          Approve {request.title}
                        </label>
                        <p className="font-medium">
                          {result?.outcome === "new_opportunity"
                            ? "Create NEW opportunity"
                            : "Link to EXISTING opportunity"}
                        </p>
                        <h4 className="font-medium">
                          {result?.outcome === "new_opportunity"
                            ? result.proposed_name
                            : target?.name}
                        </h4>
                        <p className="whitespace-pre-wrap text-sm">
                          {result?.outcome === "new_opportunity"
                            ? result.proposed_problem
                            : target?.problem}
                        </p>
                        {result && (
                          <>
                            <h4 className="text-sm font-medium">Rationale</h4>
                            <AnalysisMarkdown>
                              {result.rationale_markdown}
                            </AnalysisMarkdown>
                            <h4 className="text-sm font-medium">
                              Quoted evidence
                            </h4>
                            {result.evidence.map((entry, index) => (
                              <figure
                                key={index}
                                className="border-l-2 pl-3 text-sm"
                              >
                                <blockquote>{entry.quote}</blockquote>
                                <figcaption className="text-xs text-muted-foreground">
                                  {entry.feedback_id === request.id
                                    ? "This request"
                                    : `Related request ${entry.feedback_id}`}
                                </figcaption>
                              </figure>
                            ))}
                          </>
                        )}
                      </>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={pending}
                      onClick={() => {
                        onClose();
                        onOpen(request.id);
                      }}
                    >
                      Open request to review or correct
                    </Button>
                  </article>
                );
              })}
              <div className="sticky bottom-0 space-y-3 border-t bg-background py-4">
                {error && (
                  <p role="alert" className="text-sm text-destructive">
                    {error}
                  </p>
                )}
                <p className="text-sm">
                  {approved.length} decisions selected: create {newCount} new
                  opportunities and link {approved.length - newCount} existing
                  opportunities. Approved requests move to Approved.
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button
                    disabled={pending || !canEdit || !approved.length}
                    onClick={() => void confirm()}
                  >
                    {pending
                      ? "Confirming…"
                      : `Confirm ${approved.length} approvals · ${newCount} new opportunities`}
                  </Button>
                  <Button
                    variant="outline"
                    disabled={pending}
                    onClick={() => setRevision((value) => value + 1)}
                  >
                    Refresh suggestions
                  </Button>
                  <Button variant="ghost" disabled={pending} onClick={onClose}>
                    Cancel review
                  </Button>
                </div>
              </div>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
