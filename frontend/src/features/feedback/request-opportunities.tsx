import { useEffect, useState, useRef } from "react";
import { createPortal } from "react-dom";
import {
  Button,
  SelectPanel,
  Link,
  type SelectPanelItemInput,
} from "@primer/react";
import {
  GearIcon,
  CrossReferenceIcon,
  CheckIcon,
} from "@primer/octicons-react";
import { approveRequest, type ApprovalJob } from "./request-decisions";
import { api } from "@/lib/auth-context";

type Opportunity = { id: string; name: string; problem: string };
type State = {
  linked_opportunities?: Opportunity[];
  linked_opportunity: Opportunity | null;
  run: null | {
    id: string;
    status: string;
    result: null | {
      outcome: string;
      opportunity_id?: string;
      proposed_name?: string;
      proposed_problem?: string;
    };
  };
};
export function RequestOpportunities({
  requestId,
  workspace,
  canEdit,
  status,
  actionsTarget,
  sidebarTarget,
  onConfirmed,
  onBusyChange,
}: {
  requestId: string;
  workspace: string;
  canEdit: boolean;
  status: string;
  actionsTarget: HTMLElement | null;
  sidebarTarget: HTMLElement | null;
  onConfirmed: () => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const [approval, setApproval] = useState<ApprovalJob | null>(null);
  const [state, setState] = useState<State | null>(null);
  const [selected, setSelected] = useState<Opportunity[]>([]);
  const [candidates, setCandidates] = useState<Opportunity[]>([]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [more, setMore] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [manual, setManual] = useState(false);
  const touched = useRef(false);
  const active = useRef(true);
  const savingController = useRef<AbortController | null>(null);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      savingController.current?.abort();
    };
  }, []);
  const links =
    state?.linked_opportunities ??
    (state?.linked_opportunity ? [state.linked_opportunity] : []);
  const result = state?.run?.status === "complete" ? state.run.result : null;
  useEffect(() => {
    const c = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let observedPending = false;
    async function load() {
      try {
        const next = await api<State>(
          `/feedback/${requestId}/triage`,
          { signal: c.signal },
          workspace,
        );
        if (c.signal.aborted) return;
        setState(next);
        const job = await api<ApprovalJob | null>(
          `/feedback/${requestId}/approval`,
          { signal: c.signal },
          workspace,
        );
        if (c.signal.aborted) return;
        setApproval(job);
        if (job?.status === "complete" && observedPending) {
          observedPending = false;
          onConfirmed();
        }
        if (job?.status === "queued" || job?.status === "running")
          observedPending = true;
        if (job?.status === "failed")
          setError(job.error || "Approval failed. Try again.");
        const linked =
          next.linked_opportunities ??
          (next.linked_opportunity ? [next.linked_opportunity] : []);
        let defaults = linked;
        if (
          !linked.length &&
          next.run?.status === "complete" &&
          next.run.result?.outcome === "existing_opportunity"
        ) {
          const match = await api<Opportunity>(
            `/opportunities/${next.run.result.opportunity_id}`,
            { signal: c.signal },
            workspace,
          );
          defaults = [match];
        }
        if (c.signal.aborted) return;
        if (!touched.current) {
          setSelected(defaults);
          setManual(false);
        }
        if (
          ["queued", "running"].includes(next.run?.status ?? "") ||
          ["queued", "running"].includes(job?.status ?? "")
        )
          timer = setTimeout(load, 2000);
      } catch (e) {
        if (!c.signal.aborted) setError((e as Error).message);
      }
    }
    void load();
    return () => {
      c.abort();
      clearTimeout(timer);
    };
  }, [requestId, workspace, revision]);
  useEffect(() => {
    if (!open) return;
    const c = new AbortController();
    setLoading(true);
    api<{ items: Opportunity[]; has_more: boolean }>(
      `/opportunities?search=${encodeURIComponent(query)}&limit=100`,
      { signal: c.signal },
      workspace,
    )
      .then((r) => {
        if (!c.signal.aborted) {
          setCandidates(r.items);
          setMore(r.has_more);
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [query, open, workspace]);
  async function save(approve: boolean) {
    if (busy || !state) return;
    const controller = new AbortController();
    savingController.current = controller;
    setBusy(true);
    onBusyChange?.(true);
    setError("");
    try {
      // Save explicit manual edits first. Approval then reads the latest links
      // transactionally on the server and never replaces them with an AI guess.
      if (!approve || manual) {
        await api(
          `/feedback/${requestId}/opportunities`,
          {
            method: "PUT",
            signal: controller.signal,
            body: JSON.stringify({
              opportunity_ids: selected.map((o) => o.id),
              expected_ids: links.map((o) => o.id),
              approve: false,
            }),
          },
          workspace,
        );
      }
      if (approve)
        await approveRequest(requestId, workspace, controller.signal, status);
      if (controller.signal.aborted) return;
      setOpen(false);
      touched.current = false;
      setRevision((r) => r + 1);
      if (approve) onConfirmed();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      savingController.current = null;
      onBusyChange?.(false);
      setBusy(false);
    }
  }
  const editable = canEdit && status !== "archived";
  const newSuggestion =
    !manual && !links.length && result?.outcome === "new_opportunity";
  const ready = !!state;
  const items = Array.from(
    new Map([...selected, ...candidates].map((o) => [o.id, o])).values(),
  ).map((o) => ({ id: o.id, text: o.name }));
  const selection = selected.map((o) => ({ id: o.id, text: o.name }));
  const sidebar = (
    <>
      {editable && (
        <SelectPanel
          title="Link opportunities"
          placeholder="Search opportunities"
          textInputProps={{ placeholder: "Search opportunities" }}
          inputLabel="Search opportunities"
          open={open}
          onOpenChange={setOpen}
          items={items}
          selected={selection}
          loading={loading}
          filterValue={query}
          onFilterChange={setQuery}
          onSelectedChange={(values: SelectPanelItemInput[]) => {
            const all = [...selected, ...candidates];
            setSelected(
              values
                .map((v) => all.find((o) => o.id === v.id)!)
                .filter(Boolean),
            );
            touched.current = true;
            setManual(true);
          }}
          renderAnchor={({ children: _, ...props }) => (
            <Button
              {...props}
              size="small"
              leadingVisual={GearIcon}
              disabled={busy}
            >
              Link opportunities
            </Button>
          )}
          footer={
            <div className="opportunity-picker-footer">
              {more && <p>Refine your search to see more results.</p>}
              <Button
                variant="primary"
                disabled={
                  busy || !state || (status === "triaged" && !selected.length)
                }
                onClick={() => void save(false)}
              >
                Save links
              </Button>
            </div>
          }
          message={
            !loading && !items.length
              ? {
                  title: "No opportunities found",
                  body: "Try another search, or create an opportunity first.",
                  variant: "empty",
                }
              : undefined
          }
        />
      )}
      {links.map((o) => (
        <div key={o.id} className="issue-opportunity-link">
          <CrossReferenceIcon />
          <Link href={`#opportunities?id=${o.id}`}>{o.name}</Link>
        </div>
      ))}

      {!links.length && result && (
        <div className="issue-opportunity-suggestion">
          <strong>AI suggestion</strong>
          <p>
            {result.outcome === "existing_opportunity"
              ? selected[0]?.name
              : result.outcome === "new_opportunity"
                ? result.proposed_name
                : "Needs clarification"}
          </p>
          {newSuggestion && <p>{result.proposed_problem}</p>}
        </div>
      )}

      {error && <p role="alert">{error}</p>}
    </>
  );
  return (
    <>
      {sidebarTarget && createPortal(sidebar, sidebarTarget)}
      {actionsTarget &&
        createPortal(
          <Button
            size="small"
            variant="primary"
            leadingVisual={CheckIcon}
            disabled={
              !editable ||
              busy ||
              ["queued", "running"].includes(approval?.status ?? "") ||
              !ready ||
              status === "triaged"
            }
            onClick={() => void save(true)}
          >
            {busy || ["queued", "running"].includes(approval?.status ?? "")
              ? "Linking…"
              : status === "triaged"
                ? "Approved"
                : "Approve"}
          </Button>,
          actionsTarget,
        )}
    </>
  );
}
