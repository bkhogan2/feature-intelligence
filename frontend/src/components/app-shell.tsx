import { UpdatesUnreadBadge } from "@/features/updates/updates-table";
import {
  getShellLayoutStyle,
  type ShellLayout,
  type ShellHeader,
  type ShellHeaderStyle,
  type ShellRails,
} from "@/lib/shell-layout";
import {
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import {
  Check,
  ChevronsUpDown,
  LogOut,
  Settings,
  Plus,
  Inbox,
  Boxes,
  ListTodo,
  Bell,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { BillingSidebarAction } from "@/features/billing/billing-sidebar-action";
import { APP } from "@/lib/app-config";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  useSidebar,
} from "@/components/ui/sidebar";
import { useResizablePanel } from "@/hooks/use-resizable-panel";
import { PanelResizeHandle } from "./panel-resize-handle";
import { RightSidebar } from "./right-sidebar";
import "./app-shell.css";
import "./shell-layout.css";

export function AppShell({
  page,
  navigationContent,
  flushContent = false,
  title,
  children,
  layout = APP.layout,
  rightSidebarEnabled = true,
  onRightSidebarEnabledChange,
}: {
  navigationContent?: ReactNode;
  flushContent?: boolean;
  layout?: ShellLayout;
  header?: ShellHeader;
  headerStyle?: ShellHeaderStyle;
  rails?: ShellRails;
  rightSidebarEnabled?: boolean;
  onRightSidebarEnabledChange?: (enabled: boolean) => void;
  page: string;
  title: string;
  children: ReactNode;
}) {
  const auth = useAuth();
  const navigationPanel = useResizablePanel(
    APP.navigationPanel,
    "product-navigation-width",
  );
  const [rightOpen, setRightOpen] = useState(false);
  const [pageToggleHost, setPageToggleHost] = useState<HTMLDivElement | null>(
    null,
  );
  const previousEnabled = useRef(rightSidebarEnabled);
  useLayoutEffect(() => {
    if (rightSidebarEnabled && !previousEnabled.current) setRightOpen(true);
    previousEnabled.current = rightSidebarEnabled;
  }, [rightSidebarEnabled]);
  if (!auth.user || !auth.active) return null;
  const layoutStyle = {
    ...getShellLayoutStyle(layout, true, rightOpen && rightSidebarEnabled),
    "--sidebar-width": `${navigationPanel.width}px`,
  } as CSSProperties;
  return (
    <SidebarProvider
      open
      keyboardShortcut={null}
      className="app-shell composable-shell h-svh flex-col overflow-hidden bg-content-surface text-content-surface-foreground"
      style={layoutStyle}
      data-layout={layout}
      data-header="content"
      data-header-style="standard"
      data-rails="none"
    >
      <div className="composable-shell-row flex min-h-0 min-w-0 flex-1">
        <div className="composable-shell-body flex min-h-0 min-w-0 flex-1">
          <WorkspaceSidebar
            navigationContent={navigationContent}
            page={page}
            panel={navigationPanel}
          />
          <section className="composable-center flex min-h-0 min-w-0 flex-1 flex-col bg-content-surface">
            <header
              aria-label="Page header"
              className="composable-shell-header relative flex h-11 shrink-0 items-center gap-2 border-b px-5"
            >
              <h1 className="truncate text-[13px] font-medium">{title}</h1>
              <div
                ref={setPageToggleHost}
                className="composable-header-toggle-host ml-auto flex shrink-0 items-center"
              />
            </header>
            <div
              className={
                flushContent
                  ? "composable-page-scroll min-h-0 flex-1 overflow-hidden"
                  : "composable-page-scroll min-h-0 flex-1 overflow-y-auto"
              }
            >
              <main
                aria-label={title}
                className={
                  flushContent
                    ? "flex h-full min-h-0 min-w-0 flex-col"
                    : "flex min-h-full min-w-0 flex-col gap-4 p-6"
                }
              >
                {children}
              </main>
            </div>
          </section>
          <RightSidebar
            enabled={rightSidebarEnabled}
            onEnabledChange={onRightSidebarEnabledChange}
            open={rightOpen}
            onOpenChange={setRightOpen}
            layoutStyle={layoutStyle}
            contained={false}
            plain
            toggleHost={pageToggleHost}
          />
        </div>
      </div>
    </SidebarProvider>
  );
}

function WorkspaceSidebar({
  navigationContent,
  page,
  panel,
}: {
  navigationContent?: ReactNode;
  panel: ReturnType<typeof useResizablePanel>;
  page: string;
}) {
  const { setOpenMobile } = useSidebar();
  return (
    <Sidebar collapsible="none" className="workspace-sidebar relative shrink-0">
      <div className="navigation-sidebar shell-panel shell-panel--left relative transition-none flex min-h-0 min-w-0 flex-1 flex-col bg-sidebar text-sidebar-foreground">
        <SidebarHeader>
          <WorkspaceSwitcher />
        </SidebarHeader>
        <SidebarContent>
          {navigationContent ?? (
            <SidebarGroup>
              <SidebarGroupContent>
                <SidebarMenu>
                  {[
                    { id: "feedback", title: "Capture feedback", icon: Plus },
                    { id: "inbox", title: "Requests", icon: Inbox },
                    {
                      id: "opportunities",
                      title: "Opportunities",
                      icon: Boxes,
                    },
                    { id: "tasks", title: "Tasks", icon: ListTodo },
                    { id: "updates", title: "Notifications", icon: Bell },
                    { id: "settings", title: "Settings", icon: Settings },
                  ].map((item) => (
                    <SidebarMenuItem key={item.id}>
                      <SidebarMenuButton
                        asChild
                        className="data-[active=true]:font-medium"
                        isActive={page === item.id}
                      >
                        <a
                          href={`#${item.id}`}
                          aria-current={page === item.id ? "page" : undefined}
                          onClick={() => setOpenMobile(false)}
                        >
                          <item.icon />
                          <span>{item.title}</span>
                          {item.id === "updates" && <UpdatesUnreadBadge />}
                        </a>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          )}
        </SidebarContent>
        <SidebarFooter>
          <BillingSidebarAction onNavigate={() => setOpenMobile(false)} />
          <AccountMenu />
        </SidebarFooter>
      </div>
      <PanelResizeHandle
        edge="right"
        label="Resize navigation sidebar"
        width={panel.width}
        min={panel.min}
        max={panel.max}
        step={APP.navigationPanel.keyboardStep}
        onResize={panel.resize}
      />
    </Sidebar>
  );
}
function WorkspaceSwitcher() {
  const auth = useAuth();
  const { isMobile, setOpenMobile } = useSidebar();
  if (!auth.active) return null;
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton
              size="lg"
              aria-label="Switch workspace"
              title={auth.active.workspace_name}
            >
              <div className="flex size-6 shrink-0 items-center justify-center rounded-md bg-sidebar-accent text-sidebar-foreground">
                <APP.icon className="size-4" />
              </div>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-medium">
                  {APP.workspaceDisplayName(auth.active.workspace_name)}
                </span>
              </div>
              <ChevronsUpDown className="ml-auto size-4" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="start"
            side={isMobile ? "bottom" : "right"}
            className="min-w-56"
          >
            <DropdownMenuLabel>Workspaces</DropdownMenuLabel>
            {auth.memberships.map((m) => (
              <DropdownMenuItem
                key={m.workspace_slug}
                onSelect={() => {
                  auth.selectWorkspace(m.workspace_slug);
                  setOpenMobile(false);
                }}
              >
                {m.workspace_name}
                {auth.active?.workspace_slug === m.workspace_slug && (
                  <Check className="ml-auto size-4" />
                )}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
function AccountMenu() {
  const auth = useAuth();
  const { isMobile, setOpenMobile } = useSidebar();
  const [error, setError] = useState("");
  if (!auth.user) return null;
  const name = auth.user.email.split("@")[0];
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton size="lg" aria-label="Account menu">
              <Avatar className="size-6 shrink-0 rounded-full">
                <AvatarFallback className="rounded-full text-[10px]">
                  {name.slice(0, 2).toUpperCase()}
                </AvatarFallback>
              </Avatar>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-medium">{name}</span>
              </div>
              <ChevronsUpDown className="ml-auto size-4" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            side={isMobile ? "bottom" : "right"}
            align="end"
            className="min-w-56"
          >
            <DropdownMenuLabel className="max-w-[min(28rem,80vw)] whitespace-normal break-all">
              {auth.user.email}
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <a href="#settings" onClick={() => setOpenMobile(false)}>
                <Settings />
                Settings
              </a>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={() =>
                void auth.signOut().catch((e) => setError(e.message))
              }
            >
              <LogOut />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        {error && (
          <p role="alert" className="px-2 text-xs">
            {error}
          </p>
        )}
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
