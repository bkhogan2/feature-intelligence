import { InboxPanel } from "@/features/feedback/inbox-panel";
import { FeedbackPanel } from "@/features/feedback/feedback-panel";
import { AppShell } from "@/components/app-shell";
import { APP } from "@/lib/app-config";
import { ActivityPanel } from "@/features/demo/activity-panel";
import { HomePage } from "@/features/demo/home-page";
import { InvitationPanel } from "@/features/workspace/invitation-panel";
import { SettingsPage } from "@/features/settings/settings-page";
import { UpdatesPage } from "@/features/updates/submitter-updates";
import { TasksPage } from "@/features/tasks/tasks-page";
import { OpportunitiesPage } from "@/features/opportunities/opportunities-page";
import { useAppearance } from "@/features/appearance/use-appearance";
import { useAuth } from "@/lib/auth-context";
import { LoginPage } from "@/components/login-page";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

const pages = APP.pages;
function currentPage() {
  if (!window.location.hash || window.location.hash === "#login")
    return "login";
  const id = window.location.hash.slice(1).split("?")[0];
  return pages.some((p) => p.id === id) ? id : "home";
}
export function App() {
  const auth = useAuth();
  const [pendingInvite, setPendingInvite] = useState(() =>
    new URLSearchParams(window.location.hash.slice(1)).get("invite"),
  );
  const [notice, setNotice] = useState("");
  const [page, setPage] = useState(currentPage);
  const appearance = useAppearance(auth.user?.subject);
  const {
    layout,
    header,
    headerStyle,
    rails,
    rightSidebarEnabled,
    setRightSidebarEnabled,
  } = appearance;
  useEffect(() => {
    if (pendingInvite)
      history.replaceState(
        null,
        "",
        location.pathname + location.search + "#home",
      );
  }, [pendingInvite]);
  useEffect(() => {
    const update = () => setPage(currentPage());
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  if (auth.status === "loading")
    return (
      <div className="flex min-h-svh items-center justify-center text-sm text-muted-foreground">
        Loading your workspace…
      </div>
    );
  if (auth.status === "error")
    return (
      <div className="mx-auto max-w-md space-y-4 p-10">
        <p role="alert">{auth.error}</p>
        <Button
          onClick={() => {
            void auth.refresh();
          }}
        >
          Retry connection
        </Button>
      </div>
    );
  if (!auth.user)
    return (
      <LoginPage
        allowRegistration={Boolean(pendingInvite)}
        onVerified={async () => {
          await auth.refresh();
          window.location.hash = "home";
        }}
        onSignIn={async (email, password) => {
          await auth.signIn(email, password);
          window.location.hash = "home";
        }}
      />
    );
  if (pendingInvite)
    return (
      <InvitationPanel
        token={pendingInvite}
        onDone={async () => {
          setPendingInvite(null);
          await auth.refresh();
        }}
      />
    );
  if (!auth.active)
    return (
      <div className="mx-auto max-w-md space-y-5 p-10">
        <h1 className="text-2xl font-semibold">Choose a workspace</h1>
        {auth.memberships.length ? (
          auth.memberships.map((m) => (
            <Button
              key={m.workspace_slug}
              className="w-full justify-between"
              variant="outline"
              onClick={() => auth.selectWorkspace(m.workspace_slug)}
            >
              {m.workspace_name}
              <span className="text-xs">{m.role}</span>
            </Button>
          ))
        ) : (
          <p className="text-sm text-muted-foreground">
            You don't belong to a workspace yet. Ask your administrator for an
            invitation.
          </p>
        )}
        <Button
          variant="ghost"
          onClick={() => {
            void auth.signOut().catch((e) => setNotice(e.message));
          }}
        >
          Sign out
        </Button>
        {notice && <p role="alert">{notice}</p>}
      </div>
    );
  const view = page === "login" ? "home" : page;
  const active = auth.active;
  const title = pages.find((p) => p.id === view)!.title;
  return (
    <AppShell
      page={view}
      flushContent={
        view === "inbox" || view === "opportunities" || view === "tasks"
      }
      title={title}
      layout={layout}
      header={header}
      headerStyle={headerStyle}
      rails={rails}
      rightSidebarEnabled={rightSidebarEnabled}
      onRightSidebarEnabledChange={setRightSidebarEnabled}
    >
      {view === "inbox" && (
        <InboxPanel
          key={`${auth.user.subject}:${active.workspace_slug}`}
          workspace={active.workspace_slug}
          userId={auth.user.subject}
        />
      )}
      {view === "home" && <HomePage />}
      {view === "feedback" && (
        <FeedbackPanel
          key={active.workspace_slug}
          workspace={active.workspace_slug}
          role={active.role}
        />
      )}
      {view === "opportunities" && (
        <OpportunitiesPage
          key={active.workspace_slug}
          workspace={active.workspace_slug}
        />
      )}
      {view === "tasks" && (
        <div
          className="h-full min-h-0 min-w-0 overflow-y-auto"
          data-testid="tasks-scroll-pane"
        >
          <TasksPage
            key={active.workspace_slug}
            workspace={active.workspace_slug}
            userId={auth.user.subject}
          />
        </div>
      )}
      {view === "updates" && (
        <UpdatesPage
          key={`${auth.user.subject}:${active.workspace_slug}:${active.role}`}
          workspace={active.workspace_slug}
          role={active.role}
        />
      )}
      {view === "activity" && (
        <ActivityPanel
          key={active.workspace_slug}
          workspace={active.workspace_slug}
        />
      )}
      {view === "settings" && (
        <SettingsPage active={active} appearance={appearance} />
      )}
    </AppShell>
  );
}
