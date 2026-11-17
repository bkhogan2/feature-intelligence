import { useEffect, useRef, useState } from "react";
import { api, useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import type { EntitlementSnapshot } from "./entitlement-policy";
import {
  BILLING_SETTINGS_LINK,
  billingRedirect,
  currentSubscriptions,
  focusBillingSettings,
  formatPrice,
} from "./billing-policy";

type Plan = {
  key: string;
  name: string;
  currency: string;
  unit_amount: number;
  interval: string;
  interval_count: number;
};
export type BillingSummary = {
  enabled: boolean;
  mode: "test" | "live";
  manual_plan: string | null;
  has_customer: boolean;
  plans: Plan[];
  subscriptions: {
    plan_key: string | null;
    status: string;
    period_end: string | null;
    cancel_at_period_end: boolean;
    collection_paused: boolean;
    payment_confirmed: boolean;
  }[];
  entitlements: EntitlementSnapshot;
};

export function BillingPanel({
  workspace,
  role,
}: {
  workspace: string;
  role: string;
}) {
  const { user } = useAuth();
  const scope = JSON.stringify([user?.subject, workspace]);
  const currentScope = useRef(scope);
  currentScope.current = scope;
  const [state, setState] = useState<{
    scope: string;
    data?: BillingSummary;
    error?: string;
  }>();
  const [busy, setBusy] = useState(false);
  const requestVersion = useRef(0);
  const data = state?.scope === scope ? state.data : undefined;
  const error = state?.scope === scope ? state.error : undefined;

  useEffect(() => {
    let alive = true;
    setBusy(false);
    const load = () => {
      const version = ++requestVersion.current;
      api<BillingSummary>("/billing", {}, workspace)
        .then((data) => {
          if (alive && version === requestVersion.current)
            setState({ scope, data });
        })
        .catch(() => {
          if (alive && version === requestVersion.current)
            setState({ scope, error: "Unable to load billing. Please retry." });
        });
    };
    load();
    window.addEventListener("focus", load);
    return () => {
      alive = false;
      window.removeEventListener("focus", load);
    };
  }, [scope, workspace]);

  async function action(
    path: "checkout" | "portal" | "refresh",
    plan?: string,
  ) {
    const version = ++requestVersion.current;
    setBusy(true);
    setState({ scope, data });
    try {
      const result = await api<BillingSummary & { url?: string }>(
        `/billing/${path}`,
        {
          method: "POST",
          ...(plan ? { body: JSON.stringify({ plan }) } : {}),
        },
        workspace,
      );
      if (currentScope.current !== scope || version !== requestVersion.current)
        return;
      if (path === "refresh") {
        setState({ scope, data: result });
        window.dispatchEvent(new Event("billing-updated"));
      } else {
        window.location.assign(billingRedirect(result.url, path));
      }
    } catch (error) {
      if (currentScope.current === scope)
        setState({
          scope,
          data,
          error:
            error instanceof Error
              ? error.message
              : "Billing failed. Please retry.",
        });
    } finally {
      if (currentScope.current === scope) setBusy(false);
    }
  }

  useEffect(() => {
    const showBilling = () => {
      if (window.location.hash === BILLING_SETTINGS_LINK)
        focusBillingSettings();
    };
    showBilling();
    window.addEventListener("hashchange", showBilling);
    return () => window.removeEventListener("hashchange", showBilling);
  }, []);

  const active = currentSubscriptions(data?.subscriptions ?? []);
  const returned = new URLSearchParams(window.location.hash.split("?")[1]).get(
    "billing",
  );
  return (
    <section className="space-y-4" aria-labelledby="billing-heading">
      <div>
        <h2
          id="billing-heading"
          tabIndex={-1}
          className="text-lg font-semibold"
        >
          Plan & billing
        </h2>
        <p className="text-sm text-muted-foreground">
          Plans unlock features. Your workspace role still controls what you can
          do.
        </p>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {!data && !error && <p className="text-sm">Loading billing…</p>}
      {data && (
        <>
          <p className="text-sm">
            Current access:{" "}
            <strong>
              {data.entitlements.billing_enabled
                ? (data.entitlements.plan ?? "No eligible plan")
                : "Plan checks disabled"}
            </strong>
          </p>
          {!data.enabled && (
            <p className="text-sm text-muted-foreground">
              Online billing is not enabled. Contact your operator for plan
              configuration.
            </p>
          )}
          {data.enabled && (
            <>
              {data.mode === "test" && (
                <p className="rounded-md border p-3 text-sm">
                  Stripe test mode — use test payment details only. No real
                  charges.
                </p>
              )}
              {returned && (
                <p role="status" className="text-sm">
                  Returned from Stripe. This does not confirm payment or change
                  access. Refresh billing to check the server-verified
                  subscription status.
                </p>
              )}
              {data.manual_plan && (
                <p className="text-sm">
                  Operator-managed plan: {data.manual_plan}. Contact your
                  operator before starting a subscription.
                </p>
              )}
              {active.map((subscription, index) => (
                <div key={index} className="rounded-md border p-3 text-sm">
                  <p>
                    {subscription.plan_key ?? "Unmapped plan"} —{" "}
                    {subscription.status.replaceAll("_", " ")}
                  </p>
                  {subscription.period_end && (
                    <p>
                      {subscription.cancel_at_period_end
                        ? "Scheduled to end"
                        : "Current access period ends"}
                      : {new Date(subscription.period_end).toLocaleString()}
                    </p>
                  )}
                  {(subscription.status === "past_due" ||
                    subscription.collection_paused ||
                    !subscription.payment_confirmed) && (
                    <p>
                      Paid feature access is not confirmed. Manage billing to
                      resolve payment or a pending plan change, then refresh.
                    </p>
                  )}
                </div>
              ))}
              {active.length > 1 && (
                <p role="alert" className="text-sm text-destructive">
                  Multiple subscriptions need operator review. Feature access is
                  paused to avoid selecting the wrong plan.
                </p>
              )}
              {role !== "admin" ? (
                <p className="text-sm text-muted-foreground">
                  Only workspace administrators can change or manage billing.
                </p>
              ) : (
                <>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      disabled={busy}
                      onClick={() => void action("refresh")}
                    >
                      {busy ? "Working…" : "Refresh billing"}
                    </Button>
                    {data.has_customer && (
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={() => void action("portal")}
                      >
                        Manage billing
                      </Button>
                    )}
                  </div>
                  {!data.manual_plan && active.length === 0 && (
                    <div className="grid gap-3 sm:grid-cols-2">
                      {data.plans.map((plan) => (
                        <div
                          key={plan.key}
                          className="space-y-3 rounded-lg border p-4"
                        >
                          <h3 className="font-medium">{plan.name}</h3>
                          <p className="text-sm">
                            {formatPrice(plan)} (before applicable taxes)
                          </p>
                          <Button
                            disabled={busy}
                            onClick={() => void action("checkout", plan.key)}
                          >
                            Subscribe to {plan.name}
                          </Button>
                        </div>
                      ))}
                      {data.plans.length === 0 && (
                        <p className="text-sm text-muted-foreground">
                          No plans are available for online checkout yet.
                        </p>
                      )}
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
