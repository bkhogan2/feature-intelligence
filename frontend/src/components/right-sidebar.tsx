import { PanelResizeHandle } from "./panel-resize-handle";
import { createPortal } from "react-dom";
import { APP } from "@/lib/app-config";
import { useResizablePanel } from "@/hooks/use-resizable-panel";
import { lazy, Suspense } from "react";
const AssistantChat = lazy(() => import("./assistant-chat"));
import { useAuth } from "@/lib/auth-context";
import { SHELL_DIMENSIONS } from "@/lib/shell-layout";
import { useId, type CSSProperties } from "react";
import { PanelRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sidebar, SidebarProvider, useSidebar } from "@/components/ui/sidebar";

export function RightSidebar({
  open,
  onOpenChange,
  layoutStyle,
  contained,
  plain = false,
  toggleHost,
  enabled = true,
  onEnabledChange,
}: {
  enabled?: boolean;
  onEnabledChange?: (enabled: boolean) => void;
  plain?: boolean;
  toggleHost?: HTMLElement | null;
  contained: boolean;
  layoutStyle: CSSProperties;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { width, resize, min, max } = useResizablePanel(
    APP.assistant.panel,
    "assistant-width",
  );
  const panelStyle = {
    ...layoutStyle,
    // Anchor to the minimum panel center, independently of its dragged width.
    "--shell-right-toggle-offset": `calc(${APP.assistant.panel.minWidth}px / 2 - 1rem + var(--workspace-frame-gap) + ${contained ? "0px" : SHELL_DIMENSIONS.railWidth})`,
    "--sidebar-width": plain
      ? `${width}px`
      : `calc(${width}px + ${SHELL_DIMENSIONS.railWidth})`,
  } as CSSProperties;
  return (
    <SidebarProvider
      className="contents"
      open={open}
      onOpenChange={onOpenChange}
      cookieName="right_sidebar_state"
      keyboardShortcut={null}
      style={panelStyle}
    >
      <RightSidebarContent
        layoutStyle={panelStyle}
        contained={contained}
        plain={plain}
        toggleHost={toggleHost}
        enabled={enabled}
        onEnabledChange={onEnabledChange}
        width={width}
        min={min}
        max={max}
        resize={resize}
      />
    </SidebarProvider>
  );
}
function RightSidebarContent({
  layoutStyle,
  contained,
  width,
  min,
  max,
  resize,
  plain,
  toggleHost,
  enabled,
  onEnabledChange,
}: {
  enabled: boolean;
  onEnabledChange?: (enabled: boolean) => void;
  plain: boolean;
  toggleHost?: HTMLElement | null;
  width: number;
  min: number;
  max: number;
  resize: (width: number) => void;
  layoutStyle: CSSProperties;
  contained: boolean;
}) {
  const panelId = useId();
  const auth = useAuth();
  const { isMobile, open, openMobile, toggleSidebar, setOpen, setOpenMobile } =
    useSidebar();
  const toggle = (
    <Button
      variant="ghost"
      size="icon"
      className={plain ? "size-8" : "right-sidebar-toggle fixed z-30 size-8"}
      aria-label="Toggle right sidebar"
      title="Toggle right sidebar"
      aria-controls={panelId}
      aria-expanded={enabled && (isMobile ? openMobile : open)}
      onClick={() => {
        if (!enabled) {
          onEnabledChange?.(true);
          if (isMobile) setOpenMobile(true);
          else setOpen(true);
        } else toggleSidebar();
      }}
    >
      <PanelRight className="size-4" />
    </Button>
  );
  return (
    <>
      {plain ? (toggleHost ? createPortal(toggle, toggleHost) : null) : toggle}
      <div className={enabled ? "contents" : "hidden"} inert={!enabled}>
        <Sidebar
          side="right"
          positioning={plain || contained ? "inline" : "fixed"}
          collapsible={plain ? "offcanvas" : "icon"}
          offsetByHeader={!plain}
          mobileWidth={SHELL_DIMENSIONS.mobileSidebarWidth}
          mobileIconWidth={SHELL_DIMENSIONS.mobileRailWidth}
          mobileStyle={layoutStyle}
          disableTransition
          contentClassName="flex-row"
          className={`border-l-0 group-data-[side=right]:border-l-0 ${contained ? "shell-contained-right-sidebar" : ""}`}
        >
          <aside
            id={panelId}
            aria-label="Right sidebar"
            className="navigation-sidebar shell-panel shell-panel--right relative flex flex-col overflow-hidden min-w-0 flex-1 bg-sidebar text-sidebar-foreground group-data-[collapsible=icon]:hidden"
          >
            <PanelResizeHandle
              edge="left"
              label="Resize assistant panel"
              width={width}
              min={min}
              max={max}
              step={APP.assistant.panel.keyboardStep}
              onResize={resize}
            />
            <Suspense
              fallback={
                <div className="p-4 text-sm text-muted-foreground">
                  Loading assistant…
                </div>
              }
            >
              <AssistantChat
                key={`${auth.user?.subject}:${auth.active?.workspace_slug}`}
              />
            </Suspense>
          </aside>
          <div
            aria-hidden="true"
            className={
              plain || contained || isMobile
                ? "hidden"
                : "w-[var(--sidebar-width-icon)] shrink-0 bg-sidebar py-3"
            }
          />
        </Sidebar>
      </div>
    </>
  );
}
