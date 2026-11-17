import { useEffect, useState } from "react";
import { api } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
export type Correction = {
  mode: "accept" | "existing" | "edit_new";
  opportunity_id?: string;
  name?: string;
  problem?: string;
  reason?: string;
};
type Opportunity = { id: string; name: string; problem: string };
export function ReviewerCorrection({
  workspace,
  proposal,
  pending,
  disabled,
  onConfirm,
}: {
  workspace: string;
  proposal: { name: string; problem: string } | null;
  pending: boolean;
  disabled: boolean;
  onConfirm: (choice: Correction) => void;
}) {
  const [mode, setMode] = useState<Correction["mode"]>("accept");
  const [search, setSearch] = useState("");
  const [options, setOptions] = useState<Opportunity[]>([]);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [target, setTarget] = useState("");
  const [name, setName] = useState(proposal?.name ?? "");
  const [problem, setProblem] = useState(proposal?.problem ?? "");
  const [reason, setReason] = useState("");
  useEffect(() => {
    if (mode !== "existing") return;
    const controller = new AbortController();
    setLoading(true);
    setTarget("");
    setError("");
    const timer = setTimeout(() => {
      void api<{ items: Opportunity[]; has_more: boolean }>(
        `/opportunities?search=${encodeURIComponent(search)}`,
        { signal: controller.signal },
        workspace,
      )
        .then((data) => {
          if (!controller.signal.aborted) {
            setOptions(data.items);
            setMore(data.has_more);
          }
        })
        .catch((err) => {
          if (!controller.signal.aborted) setError((err as Error).message);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 200);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [mode, search, workspace]);
  const chosen = options.find((o) => o.id === target);
  const valid =
    mode === "accept" ||
    (reason.trim() &&
      (mode === "existing"
        ? !!chosen && !loading && !error
        : name.trim() && problem.trim()));
  const inputClass = "w-full rounded-md border bg-background px-3 py-2 text-sm";
  return (
    <div className="space-y-3" aria-label="Reviewer correction">
      <label className="block text-sm">
        Confirmation choice
        <select
          aria-label="Confirmation choice"
          className={inputClass}
          value={mode}
          disabled={pending || disabled}
          onChange={(e) => setMode(e.target.value as Correction["mode"])}
        >
          <option value="accept">Accept original AI suggestion</option>
          <option value="existing">Choose an existing opportunity</option>
          {proposal && (
            <option value="edit_new">Edit proposed opportunity</option>
          )}
        </select>
      </label>
      {mode !== "accept" && (
        <p className="text-xs text-muted-foreground">
          Human correction draft — the original AI suggestion and evidence above
          remain unchanged. Confirming records your choice, reason, author and
          time.
        </p>
      )}
      {mode === "existing" && (
        <>
          <label className="block text-sm">
            Find workspace opportunity
            <input
              aria-label="Find workspace opportunity"
              className={inputClass}
              value={search}
              maxLength={200}
              disabled={pending || disabled}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <label className="block text-sm">
            Target opportunity
            <select
              aria-label="Target opportunity"
              className={inputClass}
              value={target}
              disabled={loading || pending || disabled}
              onChange={(e) => setTarget(e.target.value)}
            >
              <option value="">
                {loading ? "Loading…" : "Select an opportunity"}
              </option>
              {options.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </label>
          {more && (
            <p className="text-xs">
              Showing the first 30 matches. Refine the search to find another
              opportunity.
            </p>
          )}
          {!loading && !options.length && (
            <p className="text-xs">No matching opportunities.</p>
          )}
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          {chosen && (
            <div className="rounded border p-3 text-sm">
              <strong>{chosen.name}</strong>
              <p className="mt-2 whitespace-pre-wrap">{chosen.problem}</p>
            </div>
          )}
        </>
      )}
      {mode === "edit_new" && (
        <>
          <label className="block text-sm">
            Opportunity title
            <input
              aria-label="Opportunity title"
              className={inputClass}
              value={name}
              maxLength={160}
              disabled={pending || disabled}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label className="block text-sm">
            Opportunity problem
            <textarea
              aria-label="Opportunity problem"
              className={inputClass}
              rows={5}
              value={problem}
              maxLength={4000}
              disabled={pending || disabled}
              onChange={(e) => setProblem(e.target.value)}
            />
          </label>
        </>
      )}
      {mode !== "accept" && (
        <label className="block text-sm">
          Correction reason
          <textarea
            aria-label="Correction reason"
            className={inputClass}
            rows={3}
            maxLength={2000}
            value={reason}
            disabled={pending || disabled}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
      )}
      <p className="text-xs text-muted-foreground">
        Confirmation links this request and moves it to Triaged. Creating an
        opportunity recognizes a problem; it does not commit to building it.
        Already approved requests cannot be relinked here.
      </p>
      <Button
        size="sm"
        variant="outline"
        disabled={pending || disabled || !valid}
        onClick={() =>
          onConfirm(
            mode === "accept"
              ? { mode }
              : mode === "existing"
                ? { mode, opportunity_id: target, reason }
                : { mode, name, problem, reason },
          )
        }
      >
        {pending
          ? "Saving…"
          : mode === "accept"
            ? proposal
              ? "Create opportunity and link"
              : "Confirm opportunity link"
            : mode === "existing"
              ? "Confirm chosen opportunity"
              : "Create edited opportunity and link"}
      </Button>
    </div>
  );
}
