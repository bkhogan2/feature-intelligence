import { loadOpportunityPages } from "./opportunity-pagination";
import { OpportunityTasks } from "@/features/tasks/opportunity-tasks";
import { OpportunityTable } from "./opportunity-table";
import {
  opportunityStatuses,
  opportunityHref,
  readOpportunityRoute,
  chooseOpportunityId,
  type OpportunityFilter,
} from "./opportunity-route";
import { useSelectedAssistantContext } from "@/lib/assistant-context";
import { PrioritySection, type PriorityFields } from "./priority-section";
import {
  lifecycleLabels,
  priorities,
  saveManualPriority,
  saveOpportunityStatus,
} from "./opportunity-edits";
import { useEffect, useState, useCallback } from "react";
import "./opportunities.css";
import {
  ArrowLeft,
  ArrowUpRight,
  CheckCircle2,
} from "lucide-react";
import { api, useAuth } from "@/lib/auth-context";
import { IssueDiscussion } from "@/components/issue-detail/issue-discussion";
import { Button } from "@/components/ui/button";
import {
  IssueDetail,
  IssueProperty,
} from "@/components/issue-detail/issue-detail";
import {
  OpportunityDescription,
  type DescriptionFields,
} from "./opportunity-description";

import { SubmitterComposer } from "@/features/updates/submitter-updates";
import { OutcomeCheck } from "@/features/updates/outcome-check";

type OpportunitySummary = {
  id: string;
  name: string;
  status: string;
  problem: string;
  created_by: string;
  created_at: string;
  feedback_count: number;
  priority: "high" | "medium" | "low" | null;
  priority_rationale: string;
};
type Opportunity = Omit<OpportunitySummary, "feedback_count"> &
  PriorityFields &
  DescriptionFields & {
    can_edit: boolean;
    outcome_status: string;
    outcome_evidence: string;
    outcome_revision: number;
    archived?: boolean;
    feedback: {
      id: string;
      title: string;
      description: string;
      submitted_by: string;
      created_at: string;
      support_count: number;
    }[];
    analysis: { result: { rationale_markdown?: string } | null } | null;
  };

const statuses: Record<string, string> = lifecycleLabels;

function formatDate(value: string) {
  return new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function useOpportunityRoute() {
  const [route, setRoute] = useState(() =>
    readOpportunityRoute(window.location.hash),
  );
  useEffect(() => {
    const change = () => setRoute(readOpportunityRoute(window.location.hash));
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  return route;
}
export function OpportunitiesNavigation() {
  const route = useOpportunityRoute();
  return (
    <nav aria-label="Opportunity navigation" className="space-y-1 px-3 py-4">
      <p className="px-2 pb-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
        Product intelligence
      </p>
      {(
        Object.entries(opportunityStatuses) as [OpportunityFilter, string][]
      ).map(([status, label]) => (
        <Button
          key={status}
          variant={route.status === status ? "secondary" : "ghost"}
          asChild
          className="w-full justify-start gap-2"
        >
          <a
            href={opportunityHref({ ...route, status, id: null })}
            aria-current={route.status === status ? "page" : undefined}
          >
            {label}
          </a>
        </Button>
      ))}
    </nav>
  );
}

export function OpportunitiesPage({ workspace }: { workspace: string }) {
  const { user } = useAuth();
  const route = useOpportunityRoute();
  const [listRevision, setListRevision] = useState(0);
  const [items, setItems] = useState<OpportunitySummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(() =>
    new URLSearchParams(window.location.hash.split("?")[1] || "").get("id"),
  );
  const [detail, setDetail] = useState<Opportunity | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [taskActionTarget, setTaskActionTarget] =
    useState<HTMLDivElement | null>(null);
  const [assessmentTarget, setAssessmentTarget] =
    useState<HTMLDivElement | null>(null);
  const [prioritySaving, setPrioritySaving] = useState(false);
  const [priorityError, setPriorityError] = useState("");
  const [saving, setSaving] = useState(false);
  const [decisionError, setDecisionError] = useState("");

  const updatePriority = useCallback((value: PriorityFields) => {
    setDetail((current) =>
      current?.id === value.id &&
      value.priority_revision >= current.priority_revision
        ? {
            ...current,
            priority: value.priority,
            priority_rationale: value.priority_rationale,
            priority_revision: value.priority_revision,
            priority_updated_by: value.priority_updated_by,
            priority_updated_at: value.priority_updated_at,
            priority_analysis: value.priority_analysis,
            priority_context: value.priority_context,
            effort: value.effort,
            dependencies: value.dependencies,
          }
        : current,
    );
    setItems((current) =>
      current.map((item) =>
        item.id === value.id
          ? {
              ...item,
              priority: value.priority,
              priority_rationale: value.priority_rationale,
            }
          : item,
      ),
    );
  }, []);

  const updateAssessment = useCallback(
    (id: string, analysis: PriorityFields["priority_analysis"]) => {
      setDetail((current) =>
        current?.id === id
          ? { ...current, priority_analysis: analysis }
          : current,
      );
    },
    [],
  );

  useSelectedAssistantContext(
    workspace,
    "opportunity",
    !loading && !error && detail?.id === selectedId ? detail.id : null,
    detail?.name,
  );
  useEffect(() => {
    let alive = true;
    setLoading(true);
    const controller = new AbortController();
    loadOpportunityPages<OpportunitySummary>((offset) =>
      api(
        `/opportunities?status=${route.status}&include_archived=true&limit=100&offset=${offset}`,
        { signal: controller.signal },
        workspace,
      ),
    )
      .then((items) => ({ items }))
      .then(async (data) => {
        if (!alive) return;
        let linked: Opportunity | null = null;
        if (route.id && !data.items.some((item) => item.id === route.id)) {
          try {
            linked = await api<Opportunity>(
              `/opportunities/${route.id}`,
              {},
              workspace,
            );
          } catch {
            /* An unavailable deep link falls back to the filtered list. */
          }
        }
        if (!alive) return;
        const selected = route.id
          ? chooseOpportunityId(data.items, route, linked)
          : null;
        const visible =
          linked && linked.id === selected
            ? [
                ...data.items,
                { ...linked, feedback_count: linked.feedback.length },
              ]
            : data.items;
        setItems(visible);
        setSelectedId(selected);
        setError("");
        if (route.id && selected !== route.id)
          window.history.replaceState(
            null,
            "",
            opportunityHref({ ...route, id: selected }),
          );
      })
      .catch((err: Error) => alive && setError(err.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
      controller.abort();
    };
  }, [workspace, route.status, route.id, listRevision]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let alive = true;
    setError("");
    setDetail(null);
    setDecisionError("");
    setPriorityError("");
    api<Opportunity>(`/opportunities/${selectedId}`, {}, workspace)
      .then((data) => {
        if (alive) {
          setDetail(data);
        }
      })
      .catch((err: Error) => alive && setError(err.message));
    return () => {
      alive = false;
    };
  }, [workspace, selectedId]);

  async function savePriority(priority: (typeof priorities)[number]) {
    if (!detail?.can_edit || prioritySaving || priority === detail.priority)
      return;
    setPrioritySaving(true);
    setPriorityError("");
    try {
      updatePriority(await saveManualPriority(workspace, detail, priority));
    } catch (err) {
      setPriorityError((err as Error).message);
    } finally {
      setPrioritySaving(false);
    }
  }

  async function saveDecision(status: string) {
    if (!detail?.can_edit || saving || status === detail.status) return;
    setSaving(true);
    setDecisionError("");
    try {
      const updated = await saveOpportunityStatus<Opportunity>(
        workspace,
        detail.id,
        status,
        detail.status,
      );
      setDetail((current) =>
        current?.id === updated.id
          ? { ...current, status: updated.status }
          : current,
      );
      if (route.status !== "all" && updated.status !== route.status)
        setListRevision((v) => v + 1);
      setItems((current) =>
        current.map((item) =>
          item.id === updated.id ? { ...item, status: updated.status } : item,
        ),
      );
    } catch (err) {
      setDecisionError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (loading)
    return (
      <div className="p-8 text-sm text-muted-foreground">
        Loading opportunities…
      </div>
    );
  if (error)
    return (
      <div className="p-8">
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
        <Button className="mt-3" onClick={() => setListRevision((v) => v + 1)}>
          Retry loading opportunities
        </Button>
      </div>
    );
  return (
    <div className="opportunities-layout h-full min-h-0 min-w-0 flex-1">
      <div className="opportunities-panels">
        {!route.id && (
          <section className="opportunity-table-view p-6 w-full">
            {route.status !== "all" && (
              <p className="text-sm mb-3">
                Viewing {opportunityStatuses[route.status]}.{" "}
                <a className="underline" href="#opportunities">
                  Show all opportunities
                </a>
              </p>
            )}
            <OpportunityTable
              key={`${workspace}:${route.status}`}
              workspace={workspace}
              items={items}
              onRefresh={async () => {
                const data = await loadOpportunityPages<OpportunitySummary>(
                  (offset) =>
                    api(
                      `/opportunities?status=${route.status}&include_archived=true&limit=100&offset=${offset}`,
                      {},
                      workspace,
                    ),
                );
                setItems(data);
              }}
              onOpen={(id) => {
                window.location.hash = opportunityHref({ ...route, id });
              }}
            />
          </section>
        )}
        <section
          className="opportunity-detail min-w-0 shrink-0"
          hidden={!route.id}
          aria-label="Opportunity detail"
        >
          {!detail ? (
            <div className="p-8 text-sm text-muted-foreground">
              Select an opportunity.
            </div>
          ) : (
            <IssueDetail
              id={detail.id}
              title={detail.name}
              status={statuses[detail.status]}
              backHref={opportunityHref({ ...route, id: null })}
              backLabel="Opportunities"
              subtitle={
                <>
                  Created {formatDate(detail.created_at)} ·{" "}
                  {detail.feedback.length} linked requests
                </>
              }
              sidebar={
                <>
                  <IssueProperty label="Status">
                    {detail.can_edit ? (
                      <select
                        aria-label="Opportunity status"
                        className="w-full rounded-md border bg-background p-2 text-sm"
                        value={detail.status}
                        disabled={saving}
                        onChange={(event) =>
                          void saveDecision(event.target.value)
                        }
                      >
                        {Object.entries(statuses).map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                    ) : (
                      statuses[detail.status]
                    )}
                    {decisionError && (
                      <p role="alert" className="mt-2 text-sm text-destructive">
                        {decisionError}
                      </p>
                    )}
                    {detail.can_edit &&
                      !detail.archived &&
                      ["planned", "shipped", "not_pursuing"].includes(
                        detail.status,
                      ) && (
                        <div className="mt-3 space-y-2">
                          <p className="text-xs text-muted-foreground">
                            Share this decision with submitters. Nothing is sent
                            until you review and publish.
                          </p>
                          <SubmitterComposer
                            key={detail.id}
                            workspace={workspace}
                            target={{
                              type: "opportunities",
                              id: detail.id,
                              status: detail.status,
                              requests: detail.feedback,
                              requestIds: detail.feedback.map(
                                (item) => item.id,
                              ),
                            }}
                            disabled={!detail.feedback.length}
                          />
                          {!detail.feedback.length && (
                            <p className="mt-2 text-xs text-muted-foreground">
                              Link a request to publish a submitter update.
                            </p>
                          )}
                        </div>
                      )}
                  </IssueProperty>
                  <IssueProperty label="Priority">
                    {detail.can_edit ? (
                      <select
                        aria-label="Opportunity priority"
                        className="w-full rounded-md border bg-background p-2 text-sm"
                        value={detail.priority ?? ""}
                        disabled={prioritySaving}
                        onChange={(event) =>
                          void savePriority(
                            event.target.value as (typeof priorities)[number],
                          )
                        }
                      >
                        {!detail.priority && (
                          <option value="" disabled>
                            Unprioritized
                          </option>
                        )}
                        {priorities.map((value) => (
                          <option key={value} value={value}>
                            {value[0].toUpperCase() + value.slice(1)}
                          </option>
                        ))}
                      </select>
                    ) : detail.priority ? (
                      <span className="capitalize">{detail.priority}</span>
                    ) : (
                      "Unprioritized"
                    )}
                    {priorityError && (
                      <p role="alert" className="mt-2 text-sm text-destructive">
                        {priorityError}
                      </p>
                    )}
                    <div className="mt-2" ref={setAssessmentTarget} />
                  </IssueProperty>
                  {(detail.status === "shipped" ||
                    detail.outcome_revision > 0) && (
                    <OutcomeCheck
                      key={`${workspace}:${detail.id}`}
                      workspace={workspace}
                      id={detail.id}
                      initial={detail}
                      editable={
                        detail.can_edit &&
                        detail.status === "shipped" &&
                        !detail.archived
                      }
                    />
                  )}
                  <IssueProperty label="Linked evidence">
                    <div className="space-y-3">
                      {detail.feedback.map((item) => (
                        <article
                          key={item.id}
                          className="rounded-lg border p-4"
                        >
                          <a
                            href={`#inbox?status=all&id=${item.id}`}
                            className="group flex items-start gap-2 font-medium leading-snug hover:underline"
                          >
                            {item.title}
                            <ArrowUpRight className="mt-0.5 size-3.5 shrink-0 opacity-60" />
                          </a>
                          <p className="mt-2 line-clamp-4 text-sm leading-relaxed text-muted-foreground">
                            {item.description}
                          </p>
                          <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                            <CheckCircle2 className="size-3.5" />
                            {item.support_count} support
                            {item.support_count === 1 ? "" : "s"}
                          </div>
                        </article>
                      ))}
                    </div>
                  </IssueProperty>
                </>
              }
            >
              <OpportunityDescription
                key={`${workspace}:${detail.id}`}
                id={detail.id}
                author={
                  detail.analysis?.result?.rationale_markdown
                    ? "Copilot"
                    : detail.created_by === user?.subject
                      ? "You"
                      : "Workspace member"
                }
                date={detail.created_at}
                canEdit={detail.can_edit}
                workspace={workspace}
                markdown={
                  detail.description_markdown ??
                  [detail.problem, detail.analysis?.result?.rationale_markdown]
                    .filter(Boolean)
                    .join("\n\n")
                }
                revision={detail.description_revision}
                actionRef={
                  detail.can_edit && !detail.archived
                    ? setTaskActionTarget
                    : undefined
                }
                onSave={(updated) =>
                  setDetail((current) =>
                    current?.id === detail.id
                      ? { ...current, ...updated }
                      : current,
                  )
                }
              />
              <PrioritySection
                key={`priority:${workspace}:${detail.id}`}
                detail={detail}
                workspace={workspace}
                onChange={updatePriority}
                assessmentTarget={assessmentTarget}
                onAssessment={updateAssessment}
              />
              <OpportunityTasks
                key={`tasks:${workspace}:${detail.id}`}
                id={detail.id}
                name={detail.name}
                workspace={workspace}
                canAdd={detail.can_edit && !detail.archived}
                actionTarget={taskActionTarget}
              />
              <IssueDiscussion
                key={`comments:${workspace}:${detail.id}`}
                threadId={detail.id}
                workspace={workspace}
                resource="opportunities"
                userId={user?.subject}
                canEdit={detail.can_edit}
              />
            </IssueDetail>
          )}
        </section>
      </div>
    </div>
  );
}
