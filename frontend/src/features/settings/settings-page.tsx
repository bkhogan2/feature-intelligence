// Settings layout adapted from satnaing/shadcn-admin src/features/settings.
// MIT license retained in licenses/shadcn-admin.txt.
import { useEffect, useState } from "react";
import {
  Palette,
  CreditCard,
  Users,
  Settings2,
  ShieldCheck,
} from "lucide-react";
import { APP } from "@/lib/app-config";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { PeoplePanel } from "@/features/workspace/people-panel";
import { AppearanceSettings } from "@/features/appearance/appearance-settings";
import type { AppearanceController } from "@/features/appearance/use-appearance";
import type { Membership } from "@/lib/auth-context";
import { BillingPanel } from "@/features/billing/billing-panel";
import { useAuth } from "@/lib/auth-context";
import { PlatformPanel } from "@/features/platform/platform-panel";
import { SidebarNav } from "./components/sidebar-nav";

const sections = [
  { id: "appearance", title: "Appearance", icon: Palette },
  { id: "billing", title: "Plan & billing", icon: CreditCard },
  { id: "people", title: "People & invitations", icon: Users },
  { id: "application", title: "Application", icon: Settings2 },
  { id: "platform", title: "Platform admin", icon: ShieldCheck },
];
function readSection() {
  const query = new URLSearchParams(window.location.hash.split("?")[1]);
  return query.has("billing")
    ? "billing"
    : (query.get("section") ?? "appearance");
}
export function SettingsPage({
  active,
  appearance,
}: {
  active: Membership;
  appearance: AppearanceController;
}) {
  const { user } = useAuth();
  const [requested, setRequested] = useState(readSection);
  useEffect(() => {
    const update = () => setRequested(readSection());
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  const items = sections.filter(
    (item) =>
      (item.id !== "people" || active.role === "admin") &&
      (item.id !== "platform" || Boolean(user?.platform_role)),
  );
  const section = items.some((item) => item.id === requested)
    ? requested
    : "appearance";
  return (
    <div className="@container mx-auto w-full max-w-6xl">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Manage your workspace, preferences, and billing.
        </p>
      </div>
      <Separator className="my-6" />
      <div className="flex flex-col gap-6 @3xl:flex-row @3xl:gap-10">
        <aside className="shrink-0 @3xl:w-48 @3xl:sticky @3xl:top-0 @3xl:self-start">
          <SidebarNav items={items} active={section} />
        </aside>
        <div
          className="min-w-0 flex-1 pb-8"
          key={`${active.workspace_slug}:${section}`}
        >
          <div className="max-w-2xl space-y-6">
            {section === "platform" && <PlatformPanel />}
            {section === "appearance" && (
              <AppearanceSettings appearance={appearance} />
            )}
            {section === "billing" && (
              <BillingPanel
                workspace={active.workspace_slug}
                role={active.role}
              />
            )}
            {section === "people" && active.role === "admin" && (
              <PeoplePanel workspace={active.workspace_slug} />
            )}
            {section === "application" && (
              <>
                <div className="space-y-1">
                  <h2 className="text-lg font-medium">Application</h2>
                  <p className="text-sm text-muted-foreground">
                    Application details for this workspace.
                  </p>
                </div>
                <Separator />
                <div className="space-y-2">
                  <Label htmlFor="app-name">Application name</Label>
                  <Input id="app-name" value={APP.name} readOnly />
                  <p className="text-xs text-muted-foreground">
                    Managed by your application administrator.
                  </p>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
