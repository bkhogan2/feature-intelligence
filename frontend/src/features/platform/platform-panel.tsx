import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { api, useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

type Catalog = {
  role: "owner" | "admin";
  billing_enabled: boolean;
  can_edit: boolean;
  features: { key: string; description: string }[];
  plans: {
    key: string;
    name: string;
    active: boolean;
    revision: string;
    features: string[];
  }[];
};

export function PlatformPanel() {
  const { user } = useAuth();
  // Remount on identity changes so another account never inherits the catalog.
  if (!user?.platform_role) return null;
  return <PlatformCatalog key={user.subject} />;
}
function PlatformCatalog() {
  const [catalog, setCatalog] = useState<Catalog>();
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const load = () => {
      setCatalog(undefined);
      setError("");
      api<Catalog>("/platform/plans", { signal: controller.signal })
        .then((data) => {
          if (!controller.signal.aborted) setCatalog(data);
        })
        .catch(() => {
          if (!controller.signal.aborted)
            setError(
              "Platform settings could not be loaded. Your access may have changed.",
            );
        });
    };
    load();
    return () => controller.abort();
  }, [attempt]);
  return (
    <section className="space-y-6" aria-labelledby="platform-heading">
      <div className="space-y-1">
        <h2
          id="platform-heading"
          className="flex items-center gap-2 text-lg font-medium"
        >
          <ShieldCheck className="size-5" />
          Platform administration
        </h2>
        <p className="text-sm text-muted-foreground">
          Plan features across the application, independent of the selected
          workspace.
        </p>
      </div>
      <Separator />
      {error ? (
        <div role="alert" className="space-y-3">
          <p className="text-sm text-destructive">{error}</p>
          <Button
            variant="outline"
            onClick={() => setAttempt((value) => value + 1)}
          >
            Retry
          </Button>
        </div>
      ) : !catalog ? (
        <p role="status" className="text-sm text-muted-foreground">
          Loading platform settings…
        </p>
      ) : (
        <>
          <div className="rounded-lg border bg-muted/30 p-4 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">
                {catalog.role === "owner" ? "App owner" : "Platform admin"}
              </Badge>
              <Badge variant="outline">
                {catalog.can_edit ? "Plan configuration" : "Read only"}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              Only app owners can authorize platform administrators. Workspace
              invitations never grant platform access.
            </p>
          </div>
          {!catalog.billing_enabled && (
            <p role="status" className="rounded-md border p-3 text-sm">
              Plan enforcement is currently off. These assignments are saved,
              but plan checks are bypassed. Workspace permissions still apply.
            </p>
          )}
          <div className="space-y-4">
            <h3 className="text-sm font-medium">Plans & features</h3>
            {catalog.plans.length === 0 && (
              <p className="text-sm text-muted-foreground">
                No plans have been configured.
              </p>
            )}
            {catalog.plans.map((plan) => (
              <PlanCard
                key={plan.key}
                plan={plan}
                features={catalog.features}
                canEdit={catalog.can_edit}
              />
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            Changes apply to every workspace using the plan. Prices and
            subscriptions are managed separately. Platform invitations are not
            available here.
          </p>
        </>
      )}
    </section>
  );
}

function PlanCard({
  plan,
  features,
  canEdit,
}: {
  plan: Catalog["plans"][number];
  features: Catalog["features"];
  canEdit: boolean;
}) {
  const [saved, setSaved] = useState(plan);
  const [draft, setDraft] = useState(plan.features);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);
  const changed =
    [...draft].sort().join("\n") !== [...saved.features].sort().join("\n");
  async function save() {
    setBusy(true);
    setMessage("");
    setFailed(false);
    try {
      const updated = await api<Catalog["plans"][number]>(
        `/platform/plans/${encodeURIComponent(plan.key)}/features`,
        {
          method: "PATCH",
          body: JSON.stringify({ features: draft, revision: saved.revision }),
        },
      );
      setSaved(updated);
      setDraft(updated.features);
      setMessage("Plan features saved.");
    } catch (error) {
      setFailed(true);
      setMessage(
        error instanceof Error
          ? error.message
          : "Could not save plan features.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function reload() {
    setBusy(true);
    setMessage("");
    try {
      const latest = await api<Catalog>("/platform/plans");
      const updated = latest.plans.find((item) => item.key === plan.key);
      if (!updated)
        throw new Error("This plan no longer exists. Reload the page.");
      setSaved(updated);
      setDraft(updated.features);
      setFailed(false);
    } catch (error) {
      setFailed(true);
      setMessage(
        error instanceof Error ? error.message : "Could not reload plan.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="rounded-lg border">
      <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
        <div>
          <h4 className="font-medium">{saved.name}</h4>
          <p className="text-xs text-muted-foreground">{saved.key}</p>
        </div>
        <Badge variant={saved.active ? "secondary" : "outline"}>
          {saved.active ? "Active" : "Disabled"}
        </Badge>
      </div>
      <ul className="divide-y">
        {features.map((feature) => (
          <li
            key={feature.key}
            className="flex items-center justify-between gap-3 px-4 py-3"
          >
            <div className="min-w-0">
              <p className="text-sm">{feature.description}</p>
              <code className="text-xs text-muted-foreground break-all">
                {feature.key}
              </code>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={draft.includes(feature.key)}
              aria-label={`${saved.name}: ${feature.description}`}
              disabled={!canEdit || busy}
              onClick={() => {
                setDraft((current) =>
                  current.includes(feature.key)
                    ? current.filter((key) => key !== feature.key)
                    : [...current, feature.key],
                );
                setMessage("");
              }}
              className="inline-flex h-6 w-11 shrink-0 items-center rounded-full border-2 border-transparent bg-input transition-colors aria-checked:bg-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span
                className={`pointer-events-none block size-5 rounded-full bg-background shadow-sm transition-transform ${draft.includes(feature.key) ? "translate-x-5" : "translate-x-0"}`}
              />
            </button>
          </li>
        ))}
      </ul>
      {!saved.active && (
        <p className="px-4 pb-3 text-xs text-muted-foreground">
          Disabled plans grant no features. Saving assignments does not activate
          this plan.
        </p>
      )}
      {canEdit && (
        <div className="flex flex-wrap items-center gap-2 border-t px-4 py-3">
          <Button size="sm" disabled={busy || !changed} onClick={save}>
            {busy ? "Working…" : "Save changes"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={busy || !changed}
            onClick={() => {
              setDraft(saved.features);
              setMessage("");
            }}
          >
            Cancel
          </Button>
          {changed && (
            <span className="text-xs text-muted-foreground">
              Unsaved changes
            </span>
          )}
          {failed && (
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={reload}
            >
              Reload plan & discard changes
            </Button>
          )}
        </div>
      )}
      {message && (
        <p
          role={failed ? "alert" : "status"}
          className={`px-4 pb-3 text-sm ${failed ? "text-destructive" : "text-muted-foreground"}`}
        >
          {message}
        </p>
      )}
    </div>
  );
}
