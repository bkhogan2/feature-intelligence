import { afterAll, beforeAll, expect, test } from "bun:test";
import { Window } from "happy-dom";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import type { api } from "../src/lib/auth-context";
let browser: Window;
let root: Root;
const originals = new Map<string, PropertyDescriptor | undefined>();
const calls: { path: string; body: any }[] = [];
let fail = true;
let refreshes = 0;
const request = (async (path: string, options: RequestInit = {}) => {
  calls.push({ path, body: options.body && JSON.parse(String(options.body)) });
  if (path.endsWith("batch-assess"))
    return {
      id: "batch",
      status: "complete",
      items: ["alpha", "beta"].map((id) => ({
        opportunity_id: id,
        name: id,
        current_priority: "low",
        expected_revision: 3,
        expected_evidence_revision: 7,
        effort: "2 days",
        dependencies: "team",
        analysis: {
          id: `analysis-${id}`,
          status: "complete",
          result: {
            priority: "high",
            rationale: `Rationale ${id}`,
            missing_information: ["Effort unknown"],
            workflow_impact: "Impact",
            evidence_strength: "Strong",
            goals_alignment: "Aligned",
            dependencies: "Team",
          },
        },
      })),
    };
  if (fail) throw new Error("Save rejected");
  return { items: [] };
}) as typeof api;
const click = async (text: string) => {
  const button = [...document.querySelectorAll("button")].find(
    (node) => node.textContent?.trim() === text,
  )!;
  expect(button).toBeTruthy();
  await act(async () => button.click());
};
beforeAll(async () => {
  browser = new Window({ url: "http://localhost" });
  const values: Record<string, unknown> = {
    window: browser,
    document: browser.document,
    navigator: browser.navigator,
    getComputedStyle: browser.getComputedStyle.bind(browser),
    IS_REACT_ACT_ENVIRONMENT: true,
  };
  for (const name of [
    "HTMLElement",
    "HTMLInputElement",
    "HTMLSelectElement",
    "Element",
    "DocumentFragment",
    "Event",
    "CustomEvent",
    "NodeFilter",
    "MutationObserver",
    "Node",
    "ResizeObserver",
  ])
    values[name] = (browser as any)[name];
  for (const [key, value] of Object.entries(values)) {
    originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, {
      value,
      configurable: true,
      writable: true,
    });
  }
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const { BatchPriority } =
    await import("../src/features/opportunities/batch-priority");
  await act(async () =>
    root.render(
      createElement(BatchPriority, {
        workspace: "test",
        selectedIds: ["alpha"],
        filteredIds: ["alpha", "beta"],
        disabled: false,
        request,
        onRefresh: async () => {
          refreshes++;
        },
      }),
    ),
  );
});
afterAll(async () => {
  await act(async () => root.unmount());
  await browser.happyDOM.abort();
  for (const [key, descriptor] of originals) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else Reflect.deleteProperty(globalThis, key);
  }
});
test("comparative review saves only explicit edited choices, retaining edits through closure and failure", async () => {
  await click("AI prioritize all filtered (2)");
  expect(calls).toHaveLength(0);
  await click("Generate suggestions");
  expect(calls).toHaveLength(1);
  expect(calls[0].body).toEqual({ opportunity_ids: ["alpha", "beta"] });
  expect(document.body.textContent).toContain("Effort unknown");
  const selected = document.querySelectorAll<HTMLInputElement>(
    'input[type="checkbox"]',
  );
  await act(async () => selected[1].click());
  const select = document.querySelector("select")!;
  await act(async () => {
    select.value = "medium";
    select.dispatchEvent(
      new browser.Event("change", { bubbles: true }) as unknown as Event,
    );
  });
  await click("Close");
  await click("Review AI batch");
  expect(document.querySelector("select")!.value).toBe("medium");
  expect(
    document.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')[1]
      .checked,
  ).toBe(false);
  await click("Save 1 reviewed priority");
  expect(document.body.textContent).toContain("Save rejected");
  expect(refreshes).toBe(0);
  expect(document.querySelector("select")!.value).toBe("medium");
  const saved = calls[1].body.items;
  expect(saved).toEqual([
    {
      opportunity_id: "alpha",
      priority: "medium",
      rationale: "Rationale alpha",
      effort: "2 days",
      dependencies: "team",
      expected_revision: 3,
      expected_evidence_revision: 7,
      accepted_analysis_id: null,
    },
  ]);
  fail = false;
  await click("Save 1 reviewed priority");
  expect(refreshes).toBe(1);
  expect(document.body.textContent).toContain(
    "Saved priorities for 1 opportunities",
  );
});
