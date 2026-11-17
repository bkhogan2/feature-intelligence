import type { CSSProperties } from "react";

// Layout is independent of the color palette and light/dark appearance.
export const SHELL_LAYOUTS = {
  "no-inset": {
    label: "No inset",
    insetLeft: false,
    insetRight: false,
    containRightSidebar: false,
  },
  "left-inset": {
    label: "Left inset",
    insetLeft: true,
    insetRight: false,
    containRightSidebar: true,
  },
  "dual-inset": {
    label: "Dual inset",
    insetLeft: true,
    insetRight: true,
    containRightSidebar: false,
  },
} as const;
export type ShellLayout = keyof typeof SHELL_LAYOUTS;
export const DEFAULT_SHELL_LAYOUT: ShellLayout = "dual-inset";
export const SHELL_DIMENSIONS = {
  sidebarWidth: "20.275rem",
  railWidth: "4.275rem",
  mobileSidebarWidth: "19.275rem",
  mobileRailWidth: "4.275rem",
  headerHeight: "3rem",
  insetRadius: "1rem",
  frameGap: "0.3rem",
  mobileFrameGap: "0.15rem",
} as const;

export const SHELL_RAILS = {
  none: "None",
  left: "Left",
  right: "Right",
  both: "Both",
} as const;
export type ShellRails = keyof typeof SHELL_RAILS;
export function parseShellRails(value: unknown): ShellRails {
  return typeof value === "string" && Object.hasOwn(SHELL_RAILS, value)
    ? (value as ShellRails)
    : "none";
}
export function hasActivityRail(rails: ShellRails, side: "left" | "right") {
  return rails === "both" || rails === side;
}

export const SHELL_HEADER_STYLES = {
  standard: "Standard",
  centered: "Centered branding",
} as const;
export type ShellHeaderStyle = keyof typeof SHELL_HEADER_STYLES;
export function parseShellHeaderStyle(value: unknown): ShellHeaderStyle {
  return value === "centered" ? "centered" : "standard";
}
export const CLASSIC_SHELL_PRESET = {
  layout: "left-inset",
  header: "site",
  headerStyle: "centered",
  rails: "left",
  rightSidebarEnabled: false,
} as const;

export const SHELL_HEADERS = {
  content: "Page header (Sidebar 15)",
  site: "Sticky site header (Sidebar 16)",
} as const;
export type ShellHeader = keyof typeof SHELL_HEADERS;
export function parseShellHeader(value: unknown): ShellHeader {
  return value === "site" ? "site" : "content";
}

export function parseShellLayout(value: unknown): ShellLayout {
  if (value === "sidebar-15") return "no-inset";
  return typeof value === "string" && Object.hasOwn(SHELL_LAYOUTS, value)
    ? (value as ShellLayout)
    : DEFAULT_SHELL_LAYOUT;
}

type LayoutStyle = CSSProperties & Record<`--${string}`, string>;
export function getShellLayoutStyle(
  layout: ShellLayout,
  leftOpen: boolean,
  rightOpen: boolean,
): LayoutStyle {
  const preset = SHELL_LAYOUTS[parseShellLayout(layout)];
  const leftRadius = preset.insetLeft ? SHELL_DIMENSIONS.insetRadius : "0px";
  const rightRadius = preset.insetRight ? SHELL_DIMENSIONS.insetRadius : "0px";
  const hasInset = preset.insetLeft || preset.insetRight;
  const shadows = hasInset ? ["var(--shell-top-edge)"] : [];
  if (!leftOpen && preset.insetLeft)
    shadows.unshift("var(--shell-left-edge-shadow)");
  if (preset.containRightSidebar || (!rightOpen && preset.insetRight))
    shadows.unshift("var(--shell-right-edge-shadow)");
  return {
    "--sidebar-width": SHELL_DIMENSIONS.sidebarWidth,
    "--sidebar-width-icon": SHELL_DIMENSIONS.railWidth,
    "--app-header-height": SHELL_DIMENSIONS.headerHeight,
    // Header controls use the shell dimensions, never the resizable panel width.
    "--shell-header-toggle-offset": `calc(${SHELL_DIMENSIONS.railWidth} + (${SHELL_DIMENSIONS.sidebarWidth} - ${SHELL_DIMENSIONS.railWidth}) / 2 - 1rem)`,
    "--shell-frame-gap-desktop": hasInset ? SHELL_DIMENSIONS.frameGap : "0px",
    "--shell-frame-gap-mobile": hasInset
      ? SHELL_DIMENSIONS.mobileFrameGap
      : "0px",
    "--shell-left-radius": leftRadius,
    "--shell-right-radius": rightRadius,
    "--shell-frame-left-radius": leftOpen ? "0px" : leftRadius,
    "--shell-frame-right-radius": hasInset
      ? SHELL_DIMENSIONS.insetRadius
      : "0px",
    "--shell-frame-gap": "var(--workspace-frame-gap)",
    "--shell-frame-shadow": shadows.join(", ") || "none",
    "--shell-content-left-radius":
      preset.containRightSidebar || leftOpen ? "0px" : leftRadius,
    "--shell-content-right-radius":
      preset.containRightSidebar || rightOpen
        ? "0px"
        : hasInset
          ? SHELL_DIMENSIONS.insetRadius
          : "0px",
    "--shell-content-mobile-right-radius": hasInset
      ? SHELL_DIMENSIONS.insetRadius
      : "0px",
    "--shell-content-inline-end-gap": "0px",
    "--shell-left-panel-gap": preset.insetLeft
      ? "var(--workspace-frame-gap)"
      : "0px",
    "--shell-right-panel-gap": preset.insetRight
      ? "var(--workspace-frame-gap)"
      : "0px",
    "--shell-content-gap":
      !preset.containRightSidebar && (preset.insetLeft || preset.insetRight)
        ? "var(--workspace-frame-gap)"
        : "0px",
    "--shell-left-panel-shadow": preset.insetLeft
      ? "var(--shell-left-edge-shadow), var(--shell-top-edge)"
      : "none",
    "--shell-right-panel-shadow": preset.insetRight
      ? "var(--shell-right-edge-shadow), var(--shell-top-edge)"
      : "none",
    "--shell-content-shadow": preset.containRightSidebar
      ? "none"
      : shadows.join(", ") || "none",
  };
}
