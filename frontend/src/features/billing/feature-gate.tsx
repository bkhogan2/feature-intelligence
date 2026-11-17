import { useEffect, useState, type ReactNode } from "react";
import { api, useAuth } from "@/lib/auth-context";

import { hasFeature, type EntitlementSnapshot } from "./entitlement-policy";

export function useEntitlements(workspace: string) {
  const { user } = useAuth();
  const scope = JSON.stringify([user?.subject, workspace]);
  const [state, setState] = useState<{
    scope: string;
    data?: EntitlementSnapshot;
    error?: string;
  }>();
  useEffect(() => {
    let alive = true;
    const load = () => {
      api<EntitlementSnapshot>("/entitlements", {}, workspace)
        .then((data) => {
          if (alive) setState({ scope, data });
        })
        .catch(() => {
          if (alive) setState({ scope, error: "Unable to load plan access." });
        });
    };
    load();
    window.addEventListener("focus", load);
    window.addEventListener("billing-updated", load);
    return () => {
      alive = false;
      window.removeEventListener("focus", load);
      window.removeEventListener("billing-updated", load);
    };
  }, [scope, workspace]);
  // Do not render the previous workspace/user's permissions during a switch.
  return state?.scope === scope ? state : undefined;
}

export function FeatureGate({
  feature,
  snapshot,
  children,
  fallback = (
    <p className="text-sm text-muted-foreground">
      This feature is not included in your workspace plan. Contact your
      operator.
    </p>
  ),
}: {
  feature: string;
  snapshot?: EntitlementSnapshot;
  children: ReactNode;
  fallback?: ReactNode;
}) {
  // Presentation only. Backend checks remain authoritative on every mutation.
  return hasFeature(snapshot, feature) ? children : fallback;
}
