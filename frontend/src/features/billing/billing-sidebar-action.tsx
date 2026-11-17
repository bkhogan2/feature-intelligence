import { useEffect, useState } from "react";
import { ArrowUpRight, CreditCard } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, useAuth } from "@/lib/auth-context";
import type { BillingSummary } from "./billing-panel";
import {
  BILLING_SETTINGS_LINK,
  currentSubscriptions,
  focusBillingSettings,
} from "./billing-policy";

export function BillingSidebarAction({
  onNavigate,
}: {
  onNavigate: () => void;
}) {
  const { user, active } = useAuth();
  if (!user || active?.role !== "admin") return null;

  return (
    <WorkspaceBillingAction
      key={JSON.stringify([user.subject, active.workspace_slug])}
      workspace={active.workspace_slug}
      onNavigate={onNavigate}
    />
  );
}

function WorkspaceBillingAction({
  workspace,
  onNavigate,
}: {
  workspace: string;
  onNavigate: () => void;
}) {
  const [summary, setSummary] = useState<BillingSummary>();
  useEffect(() => {
    let request: AbortController | undefined;
    const load = () => {
      request?.abort();
      const current = new AbortController();
      request = current;
      api<BillingSummary>("/billing", { signal: current.signal }, workspace)
        .then((result) => {
          if (!current.signal.aborted) setSummary(result);
        })
        .catch(() => {
          if (!current.signal.aborted) setSummary(undefined);
        });
    };
    load();
    window.addEventListener("focus", load);
    window.addEventListener("billing-updated", load);
    return () => {
      request?.abort();
      window.removeEventListener("focus", load);
      window.removeEventListener("billing-updated", load);
    };
  }, [workspace]);

  if (!summary?.enabled) return null;
  const hasSubscription =
    currentSubscriptions(summary.subscriptions).length > 0;
  const canSubscribe =
    !summary.manual_plan && !hasSubscription && summary.plans.length > 0;
  if (!canSubscribe && !summary.has_customer && !hasSubscription) return null;
  const Icon = canSubscribe ? ArrowUpRight : CreditCard;

  return (
    <Button
      asChild
      size="sm"
      variant={canSubscribe ? "default" : "outline"}
      className="w-full"
    >
      <a
        href={BILLING_SETTINGS_LINK}
        onClick={() => {
          onNavigate();
          if (window.location.hash === BILLING_SETTINGS_LINK)
            focusBillingSettings();
        }}
      >
        <Icon aria-hidden="true" />
        {canSubscribe ? "Upgrade" : "Billing"}
      </a>
    </Button>
  );
}
