import { useEffect, useState } from "react";
import { api } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
type Settings = {
  enabled: boolean;
  priority_enabled: boolean;
  daily_budget_usd: number | string;
  reserved_today_usd: number | string;
  can_edit: boolean;
};
export function AutoTriageSettings({ workspace }: { workspace: string }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [priorityEnabled, setPriorityEnabled] = useState(false);
  const [budget, setBudget] = useState("0.25");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    let alive = true;
    api<Settings>("/triage/automation", {}, workspace)
      .then((value) => {
        if (alive) {
          setSettings(value);
          setEnabled(value.enabled);
          setPriorityEnabled(value.priority_enabled);
          setBudget(String(value.daily_budget_usd));
        }
      })
      .catch((e: Error) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [workspace]);
  async function save() {
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      const value = await api<Settings>(
        "/triage/automation",
        {
          method: "PUT",
          body: JSON.stringify({
            enabled,
            priority_enabled: priorityEnabled,
            daily_budget_usd: Number(budget),
          }),
        },
        workspace,
      );
      setSettings(value);
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      aria-label="Automatic triage settings"
      className="space-y-3 rounded-xl border p-5"
    >
      <h2 className="font-semibold">
        Automatic triage and priority suggestions
      </h2>
      <p className="text-sm text-muted-foreground">
        Workspace opt-in: new submissions queue the same three-outcome analysis.
        Original feedback stays New until a PM approves creating or linking an
        opportunity. Manual Analyze remains available when automatic triage is
        off.
      </p>
      {settings && (
        <>
          <p className="text-sm font-medium">
            {settings.enabled
              ? "On for this workspace"
              : "Off for this workspace"}{" "}
            · Priority after approval {settings.priority_enabled ? "On" : "Off"}{" "}
            · ${Number(settings.reserved_today_usd).toFixed(2)} allocated today
            (UTC)
          </p>
          {settings.can_edit && (
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                void save();
              }}
            >
              <label className="flex items-center gap-2 text-sm">
                <input
                  aria-label="Enable automatic triage"
                  type="checkbox"
                  checked={enabled}
                  disabled={busy}
                  onChange={(e) => setEnabled(e.target.checked)}
                />
                Enable automatic triage for this workspace
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  aria-label="Enable automatic priority after approval"
                  type="checkbox"
                  checked={priorityEnabled}
                  disabled={busy}
                  onChange={(e) => setPriorityEnabled(e.target.checked)}
                />
                Assess priority automatically after PM triage approval
              </label>
              <p className="text-xs text-muted-foreground">
                Approval queues a priority suggestion for the actual chosen
                opportunity using combined linked evidence. Priority acceptance
                and lifecycle decisions remain separate human actions. Existing
                confirmed priority, effort and status are never changed
                automatically. No backfill of past approvals.
              </p>
              <label className="block text-sm">
                Shared daily automatic run allocation (USD)
                <input
                  aria-label="Daily automatic run allocation"
                  className="mt-1 block w-32 rounded border bg-background p-2"
                  type="number"
                  min="0.05"
                  max="5"
                  step="0.05"
                  value={budget}
                  disabled={busy}
                  onChange={(e) => setBudget(e.target.value)}
                  required
                />
              </label>
              <Button disabled={busy} type="submit">
                {busy ? "Saving…" : "Save automatic triage settings"}
              </Button>
            </form>
          )}
          <p className="text-xs text-muted-foreground">
            Triage and priority share this allocation. Each automatic start
            reserves $0.05; failed/interrupted attempts retain that allocation.
            The server pauses queued work at the daily allocation. The model
            provider can exceed its per-run SDK budget on its final call, so
            this is not a hard billing cap. Reported overruns count against
            later starts. Manual retries have a separate explicit per-run
            budget.
          </p>
          <p className="text-xs text-muted-foreground">
            Queued work survives restart. Interrupted running work becomes
            Failed after its deadline and needs an explicit retry to avoid
            duplicate provider charges. Turning either opt-in off pauses its
            pending work; it does not remove saved requests.
          </p>
        </>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {saved && (
        <p role="status" className="text-sm">
          Automatic triage settings saved.
        </p>
      )}
    </section>
  );
}
