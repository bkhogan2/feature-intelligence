import { describe, expect, test } from "bun:test";
import {
  DEFAULT_SHELL_LAYOUT,
  SHELL_LAYOUTS,
  getShellLayoutStyle,
  parseShellLayout,
  parseShellHeader,
  CLASSIC_SHELL_PRESET,
  parseShellHeaderStyle,
  parseShellRails,
  hasActivityRail,
} from "../src/lib/shell-layout";

describe("shell layout contracts", () => {
  test("classic preset composes existing independent choices", () => {
    expect(CLASSIC_SHELL_PRESET).toEqual({
      layout: "left-inset",
      header: "site",
      headerStyle: "centered",
      rails: "left",
      rightSidebarEnabled: false,
    });
    expect(parseShellHeaderStyle("centered")).toBe("centered");
    for (const value of [null, "invalid", {}, "__proto__"])
      expect(parseShellHeaderStyle(value)).toBe("standard");
  });
  test("activity rails can be selected independently on either side", () => {
    for (const rails of ["none", "left", "right", "both"] as const) {
      expect(parseShellRails(rails)).toBe(rails);
      expect(hasActivityRail(rails, "left")).toBe(
        rails === "left" || rails === "both",
      );
      expect(hasActivityRail(rails, "right")).toBe(
        rails === "right" || rails === "both",
      );
    }
    for (const value of [null, {}, "__proto__", "toString"])
      expect(parseShellRails(value)).toBe("none");
  });
  test("legacy template preference migrates to independent inset and header settings", () => {
    expect(parseShellLayout("sidebar-15")).toBe("no-inset");
    expect(parseShellHeader("site")).toBe("site");
    for (const value of [null, "invalid", "__proto__", {}])
      expect(parseShellHeader(value)).toBe("content");
  });

  test("unknown or corrupted saved values safely retain the reviewed default", () => {
    for (const value of [
      null,
      undefined,
      "",
      "prototype",
      "__proto__",
      "toString",
      {},
      1,
    ])
      expect(parseShellLayout(value)).toBe(DEFAULT_SHELL_LAYOUT);
    expect(parseShellLayout("left-inset")).toBe("left-inset");
  });
  test("switching layout preserves left geometry, dimensions and color independence", () => {
    const left = getShellLayoutStyle("left-inset", true, true);
    const dual = getShellLayoutStyle("dual-inset", true, true);
    for (const key of [
      "--sidebar-width",
      "--sidebar-width-icon",
      "--app-header-height",
      "--shell-left-radius",
      "--shell-left-panel-shadow",
    ] as const)
      expect(left[key]).toBe(dual[key]);
    expect(left["--shell-right-radius"]).toBe("0px");
    expect(dual["--shell-right-radius"]).not.toBe("0px");
    for (const style of [left, dual])
      for (const key of [
        "--primary",
        "--background",
        "--foreground",
        "--navigation-sidebar",
      ])
        expect(style).not.toHaveProperty(key);
  });
  test("left inset frames the right sidebar inside the outer workspace, not the center column", () => {
    for (const rightOpen of [true, false]) {
      const style = getShellLayoutStyle("left-inset", true, rightOpen);
      expect(SHELL_LAYOUTS["left-inset"].containRightSidebar).toBe(true);
      expect(style["--shell-frame-right-radius"]).not.toBe("0px");
      expect(style["--shell-frame-gap"]).toBe("var(--workspace-frame-gap)");
      expect(style["--shell-content-right-radius"]).toBe("0px");
      expect(style["--shell-content-inline-end-gap"]).toBe("0px");
      expect(style["--shell-content-gap"]).toBe("0px");
      expect(style["--sidebar-width"]).toBe(
        getShellLayoutStyle("dual-inset", true, rightOpen)["--sidebar-width"],
      );
    }
  });
  for (const layout of Object.keys(
    SHELL_LAYOUTS,
  ) as (keyof typeof SHELL_LAYOUTS)[]) {
    test(`${layout}: independent collapse states expose only the appropriate content corners`, () => {
      for (const leftOpen of [true, false])
        for (const rightOpen of [true, false]) {
          const style = getShellLayoutStyle(layout, leftOpen, rightOpen);
          expect(style["--shell-content-left-radius"]).toBe(
            layout === "left-inset" || leftOpen
              ? "0px"
              : style["--shell-left-radius"],
          );
          expect(style["--shell-content-right-radius"]).toBe(
            layout === "left-inset" || layout === "no-inset" || rightOpen
              ? "0px"
              : "1rem",
          );
          expect(style["--sidebar-width"]).toBe(
            getShellLayoutStyle(layout, !leftOpen, !rightOpen)[
              "--sidebar-width"
            ],
          );
        }
    });
  }
});
