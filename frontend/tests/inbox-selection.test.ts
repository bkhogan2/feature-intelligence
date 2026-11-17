import { afterAll, beforeAll, describe, expect, mock, test } from "bun:test";
import { Window } from "happy-dom";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";

const requests = ["alpha", "beta", "gamma"].map((id, i) => ({
  id,
  title: `Request ${id}`,
  description: `Original ${id}`,
  submitted_by: "me",
  created_at: "2026-11-13T00:00:00Z",
  status: "new",
  priority: null as string | null,
  support_count: i,
  supported_by_me: i === 1,
}));
const detailOpportunity = {
  id: "primer-opportunity", name: "Understand feedback outcomes", problem: "Customers need visibility into review outcomes.",
  created_by: "reviewer", created_at: "2026-11-13T00:00:00Z", status: "considering", priority: "high", priority_rationale: "Repeated requests", can_edit: true,
  effort: "", dependencies: "", priority_revision: 0, priority_updated_by: null, priority_updated_at: null, priority_analysis: null,
  analysis: {result: {rationale_markdown: "**Evidence:** Reviewers need to see what happened."}},
  description_markdown: null as string | null, description_revision: 0,
  feedback_count: 1, feedback: [requests[0]],
  decisions: [{ id: "decision-1", actor_id: "reviewer", created_at: "2026-11-14T00:00:00Z", previous_status: "considering", new_status: "considering", note: "Investigate the customer impact." }],
};
let lifecycleMode = false;
let bulkReviewMode = "";
const approvals: unknown[] = [];
let failBulk = false;
let role = "editor";
let failComment = false;
const commentBodies: string[] = [];
let manualApproval: unknown = null;
const writes: { path: string; method: string; workspace: string }[] = [];
let pendingSave: {
  signal: AbortSignal;
  resolve: (value: unknown) => void;
} | null = null;
let deferSave = false;
mock.module("../src/lib/auth-context", () => ({
  useAuth: () => ({ active: { workspace_slug: "test-workspace", role } }),
  api: async (path: string, options: RequestInit = {}, workspace: string) => {
    if (path.endsWith("/approval")) {
      if (options.method !== "POST") return null;
      if (path.includes("/ai-unavailable/")) return {status:"failed",error:"AI is unavailable"};
      const payload = JSON.parse(options.body as string);
      if (path.includes("/manual/")) manualApproval = payload;
      const item = requests.find(x => path === `/feedback/${x.id}/approval`);
      if (item) { expect(payload.expected_status).toBe(item.status); item.status = "triaged"; }
      return {status:"complete"};
    }
    if (path === "/feedback/ai-unavailable/triage") { if(options.method === "POST") throw new Error("AI is unavailable"); return {run:null, linked_opportunity:null, linked_opportunities:[]}; }
    if (path.endsWith("/status")) {
      if(failBulk) throw new Error("Decision could not be saved");
      const payload = JSON.parse(options.body as string);
      const item = requests.find(x => path === `/feedback/${x.id}/status`)!;
      expect(payload.expected_status).toBe(item.status);
      item.status = payload.status;
      return {status:item.status};
    }
    if (path === "/feedback/manual/triage") return {run:null, linked_opportunity:null, linked_opportunities:[{id:"one",name:"First opportunity",problem:"First"},{id:"two",name:"Second opportunity",problem:"Second"}]};
    if (path === "/feedback/manual/opportunities") { manualApproval = JSON.parse(options.body as string); return {status:"triaged"}; }
    if (path.startsWith("/tasks?")) return { items: [], has_more: false };
    if (path.startsWith("/opportunities?")) return { items: [detailOpportunity], has_more: false };
    if (path === "/opportunities/primer-opportunity/description" && options.method === "PUT") {
      const payload = JSON.parse(options.body as string);
      expect(payload.expected_revision).toBe(detailOpportunity.description_revision);
      detailOpportunity.description_markdown = payload.markdown;
      detailOpportunity.description_revision++;
      return {description_markdown: payload.markdown, description_revision: detailOpportunity.description_revision};
    }
    if (path === "/opportunities/primer-opportunity") return detailOpportunity;
    if (path.endsWith("/comments")) {
      if (options.method === "POST") {
        const payload = JSON.parse(options.body as string);
        commentBodies.push(payload.body);
        if (failComment) throw new Error("Comment could not be saved");
        return {...payload, author_id:"me", created_at:"2026-11-15T12:00:00Z"};
      }
      return {items: []};
    }
    if (path.startsWith("/feedback?")) {
      const status = new URLSearchParams(path.split("?")[1]).get("status");
      return {
        items: requests
          .filter(
            (x) => !lifecycleMode || status === "all" || x.status === status,
          )
          .map((x) => ({ ...x })),
        has_more: false,
      };
    }
    if (path === "/feedback/triage/confirm-batch") {
      approvals.push(JSON.parse(options.body as string));
      if (bulkReviewMode === "stale") throw new Error("Suggestion is stale");
      return { items: [] };
    }
    if (path === "/opportunities/existing")
      return {
        name: "Existing discovery",
        problem: "Existing problem",
        archived: bulkReviewMode === "archived-target",
      };
    if (bulkReviewMode && path.endsWith("/triage")) {
      const id = path.split("/")[2];
      return {
        linked_opportunity: null,
        run:
          bulkReviewMode === "empty"
            ? null
            : {
                id: `run-${id}`,
                status: id === "gamma" ? "running" : "complete",
                result: {
                  outcome:
                    id === "beta" ? "existing_opportunity" : "new_opportunity",
                  opportunity_id: "existing",
                  proposed_name: "New discovery",
                  proposed_problem: "New problem",
                  rationale_markdown: "The rationale",
                  evidence: [{ feedback_id: id, quote: "Customer evidence" }],
                },
              },
      };
    }
    if (path === "/feedback/bulk") {
      writes.push({ path, method: options.method!, workspace });
      if (failBulk) throw new Error("Save rejected");
      const payload = JSON.parse(options.body as string);
      const items = requests.filter((item) => payload.ids.includes(item.id));
      for (const item of items) {
        if ("priority" in payload) item.priority = payload.priority;
        if (payload.archived !== undefined)
          item.status = payload.archived ? "archived" : "new";
      }
      return { items: items.map((item) => ({ ...item })) };
    }
    if (path.endsWith("/confirm")) {
      requests.find((x) => path.includes(`/feedback/${x.id}/`))!.status =
        "triaged";
      return { opportunity_id: "opp" };
    }
    if (path.endsWith("/support")) {
      writes.push({ path, method: options.method!, workspace });
      if (deferSave)
        return new Promise((resolve) => {
          pendingSave = { signal: options.signal!, resolve };
        });
      return { support_count: 1, supported_by_me: true };
    }
    if (path === "/triage/config")
      return {
        enabled: lifecycleMode,
        can_analyze: lifecycleMode,
        model: "test",
        max_budget_usd: 0,
      };
    if (path.endsWith("/triage"))
      return lifecycleMode
        ? {
            run: {
              id: "run",
              status: "complete",
              model: "test",
              prompt_version: "test",
              created_at: "2026-11-13T00:00:00Z",
              result: {
                outcome: "new_opportunity",
                proposed_name: "Recognized problem",
                proposed_problem: "Problem",
                rationale_markdown: "Evidence",
                evidence: [],
              },
            },
            linked_opportunity: null,
          }
        : { run: null, linked_opportunity: null };
    throw new Error(`Unexpected API call: ${path}`);
  },
}));
let root: Root;
let host: HTMLElement;
let browser: Window;
const originals = new Map<string, PropertyDescriptor | undefined>();
const settle = async (ms = 0) => {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });
};
const select = async (id: string) => {
  const button = [
    ...host.querySelectorAll<HTMLButtonElement>("button[title]"),
  ].find((b) => b.textContent!.includes(`Request ${id}`))!;
  await act(async () => button.click());
  await settle();
};
const controls = () =>
  document.querySelectorAll<HTMLButtonElement>(
    'button[aria-label="Support this request"],button[aria-label="Remove your support"]',
  );
const detail = () => document.querySelector(".github-detail")!;

beforeAll(async () => {
  browser = new Window({ url: "http://localhost" });
  const globals = {
    window: browser,
    document: browser.document,
    navigator: browser.navigator,
    HTMLElement: browser.HTMLElement,
    HTMLInputElement: browser.HTMLInputElement,
    HTMLHeadingElement: browser.HTMLHeadingElement,
    HTMLButtonElement: browser.HTMLButtonElement,
    HTMLAnchorElement: browser.HTMLAnchorElement,
    HTMLTextAreaElement: browser.HTMLTextAreaElement,
    SVGElement: browser.SVGElement,
    HTMLFormElement: browser.HTMLFormElement,
    HTMLSelectElement: browser.HTMLSelectElement,
    Element: browser.Element,
    DocumentFragment: browser.DocumentFragment,
    Event: browser.Event,
    CustomEvent: browser.CustomEvent,
    NodeFilter: browser.NodeFilter,
    MutationObserver: browser.MutationObserver,
    getComputedStyle: browser.getComputedStyle.bind(browser),
    Node: browser.Node,
    ResizeObserver: browser.ResizeObserver,
    IS_REACT_ACT_ENVIRONMENT: true,
  };
  for (const [key, value] of Object.entries(globals)) {
    originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, {
      value,
      configurable: true,
      writable: true,
    });
  }
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const { InboxPanel } = await import("../src/features/feedback/inbox-panel");
  await act(async () =>
    root.render(
      createElement(InboxPanel, { workspace: "test-workspace", userId: "me" }),
    ),
  );
  await settle(250);
});
afterAll(async () => {
  await act(async () => root.unmount());
  browser.happyDOM.abort();
  for (const [key, descriptor] of originals) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else Reflect.deleteProperty(globalThis, key);
  }
});

describe("inbox request selection", () => {
  test("keeps exactly one support control through repeated selections, with the selected request's saved state", async () => {
    for (let i = 0; i < 18; i++) {
      const request = requests[i % requests.length];
      await select(request.id);
      expect(controls().length).toBe(1);
      expect(detail().querySelector("h1")!.textContent).toContain(
        request.title,
      );
      expect(detail().textContent).toContain(
        `${request.support_count} ${request.support_count === 1 ? "supporter" : "supporters"}`,
      );
      expect(controls()[0].getAttribute("aria-pressed")).toBe(
        String(request.supported_by_me),
      );
    }
  });
  test("attributes support to the selected request and aborts an old request's pending save on selection", async () => {
    await select("alpha");
    deferSave = true;
    await act(async () => controls()[0].click());
    expect(writes.at(-1)).toEqual({
      path: "/feedback/alpha/support",
      method: "POST",
      workspace: "test-workspace",
    });
    expect(controls()[0].disabled).toBe(true);
    await select("beta");
    expect(pendingSave!.signal.aborted).toBe(true);
    await act(async () =>
      pendingSave!.resolve({ support_count: 99, supported_by_me: true }),
    );
    expect(controls().length).toBe(1);
    expect(controls()[0].disabled).toBe(false);
    expect(controls()[0].getAttribute("aria-pressed")).toBe("true");
    expect(detail().textContent).toContain("1 supporter");
    expect(detail().textContent).not.toContain("99");
    deferSave = false;
    await select("gamma");
    await act(async () => controls()[0].click());
    expect(writes.at(-1)).toEqual({
      path: "/feedback/gamma/support",
      method: "POST",
      workspace: "test-workspace",
    });
    await select("alpha");
    expect(controls()[0].getAttribute("aria-pressed")).toBe("false");
    await select("gamma");
    expect(controls()[0].getAttribute("aria-pressed")).toBe("true");
  });
});

test("PM approval removes a New table row and preserves detail and discoverability in Triaged", async () => {
  lifecycleMode = true;
  window.location.hash = "#inbox?status=new";
  const { InboxPanel } = await import("../src/features/feedback/inbox-panel");
  await act(async () =>
    root.render(
      createElement(InboxPanel, {
        key: "lifecycle",
        workspace: "test-workspace",
        userId: "me",
      }),
    ),
  );
  await settle(250);
  await select("alpha");
  expect(detail().querySelector("h1")!.textContent).toContain("Request alpha");
  const approve = [
    ...document.querySelectorAll<HTMLButtonElement>("button"),
  ].find((b) => b.textContent === "Approve")!;
  expect(approve.disabled).toBe(false);
  await act(async () => approve.click());
  await settle(250);
  expect(host.querySelectorAll("tbody button[title]:not([aria-label])").length).toBe(2);
  expect(detail().querySelector("h1")!.textContent).toContain("Request alpha");
  expect(detail().textContent).toContain("Request updated.");
  await act(async () => {
    window.location.hash = "#inbox?status=triaged";
    window.dispatchEvent(new browser.Event("hashchange") as unknown as Event);
  });
  await settle(250);
  expect(host.querySelectorAll("tbody button[title]:not([aria-label])").length).toBe(1);
  await select("alpha");
  expect(detail().querySelector("h1")!.textContent).toContain("Request alpha");
  expect(detail().textContent).toContain("Original alpha");
});

test("archive persists through the API, failed restore stays archived, and viewers have no bulk controls", async () => {
  await act(async () => {
    window.location.hash = "#inbox";
    window.dispatchEvent(new browser.Event("hashchange") as unknown as Event);
  });
  await settle();
  const clickText = async (text: string) => {
    const button = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
      (b) => b.textContent === text,
    )!;
    expect(button).toBeDefined();
    await act(async () => button.click());
    await settle();
  };
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('[aria-label="Select Request beta"]')!
      .click(),
  );
  await clickText("Archive selected (1)");
  expect(writes.at(-1)).toEqual({
    path: "/feedback/bulk",
    method: "PATCH",
    workspace: "test-workspace",
  });
  expect(host.textContent).not.toContain("Show archived requests");
  await act(async () => {
    window.location.hash = "#inbox?status=archived";
    window.dispatchEvent(new browser.Event("hashchange") as unknown as Event);
  });
  await settle();
  expect(host.querySelector('button[title="Request alpha"]')).toBeNull();
  expect(host.querySelector('button[title="Request beta"]')).not.toBeNull();
  failBulk = true;
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('[aria-label="Select Request beta"]')!
      .click(),
  );
  await clickText("Restore selected (1)");
  expect(host.querySelector('[role="alert"]')!.textContent).toContain(
    "Save rejected",
  );
  expect(host.querySelector('button[title="Request beta"]')).not.toBeNull();
  failBulk = false;
  role = "viewer";
  const { InboxPanel } = await import("../src/features/feedback/inbox-panel");
  await act(async () =>
    root.render(
      createElement(InboxPanel, {
        key: "viewer",
        workspace: "test-workspace",
        userId: "me",
      }),
    ),
  );
  await settle();
  expect(
    host.querySelector('[aria-label="Select all requests on this page"]'),
  ).toBeNull();
  expect(host.querySelector('[aria-label="Bulk request actions"]')).toBeNull();
});

const clickBulkText = async (text: string) => {
  const button = [
    ...document.querySelectorAll<HTMLButtonElement>("button"),
  ].find((b) => b.textContent === text)!;
  expect(button).toBeDefined();
  await act(async () => button.click());
  await settle();
};
async function startReview(mode: string) {
  role = "editor";
  bulkReviewMode = mode;
  requests.forEach((item) => (item.status = "new"));
  window.location.hash = "#inbox?status=new";
  const { InboxPanel } = await import("../src/features/feedback/inbox-panel");
  await act(async () =>
    root.render(
      createElement(InboxPanel, {
        key: mode,
        workspace: "test-workspace",
        userId: "me",
      }),
    ),
  );
  await settle(50);
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        '[aria-label="Select all requests on this page"]',
      )!
      .click(),
  );
  await clickBulkText("Review triage");
}
test("bulk review reads suggestions without writes and approves only explicitly selected decisions", async () => {
  const beforeWrites = writes.length;
  await startReview("subset");
  expect(writes.length).toBe(beforeWrites);
  expect(approvals.length).toBe(0);
  expect(document.querySelector('[role="dialog"]')!.textContent).toContain(
    "Existing discovery",
  );
  expect(document.querySelector('[role="dialog"]')!.textContent).toContain(
    "Existing problem",
  );
  expect(document.querySelector('[role="dialog"]')!.textContent).toContain(
    "Create NEW opportunity",
  );
  expect(document.querySelector('[role="dialog"]')!.textContent).toContain(
    "Link to EXISTING opportunity",
  );
  expect(document.querySelector('[role="dialog"]')!.textContent).toContain(
    "The rationale",
  );
  expect(document.querySelector('[role="dialog"]')!.textContent).toContain(
    "Customer evidence",
  );
  expect(document.querySelector('[role="dialog"]')!.textContent).toContain(
    "Excluded: Analysis running",
  );
  const checks = document
    .querySelector('[role="dialog"]')!
    .querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
  expect(checks.length).toBe(2);
  expect([...checks].every((box) => !box.checked)).toBe(true);
  await act(async () => checks[1].click());
  expect(approvals.length).toBe(0);
  await clickBulkText("Confirm 1 approvals · 0 new opportunities");
  expect(approvals.at(-1)).toEqual({
    items: [{ feedback_id: "beta", run_id: "run-beta" }],
  });
  expect(host.querySelector('button[title="Request beta"]')).toBeNull();
  expect(
    host
      .querySelector('[aria-label="Select Request alpha"]')!
      .getAttribute("aria-checked"),
  ).toBe("true");
  expect(
    host
      .querySelector('[aria-label="Select Request gamma"]')!
      .getAttribute("aria-checked"),
  ).toBe("true");
});
test("stale bulk confirmation retains the review, approval choices and original selection", async () => {
  await startReview("stale");
  await act(async () =>
    document
      .querySelector('[role="dialog"]')!
      .querySelector<HTMLInputElement>('input[type="checkbox"]')!
      .click(),
  );
  await clickBulkText("Confirm 1 approvals · 1 new opportunities");
  expect(
    document.querySelector('[role="dialog"]')!.querySelector('[role="alert"]')!
      .textContent,
  ).toContain("Suggestion is stale");
  expect(
    document
      .querySelector('[role="dialog"]')!
      .querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked,
  ).toBe(true);
  await clickBulkText("Cancel review");
  expect(
    host
      .querySelector('[aria-label="Select Request alpha"]')!
      .getAttribute("aria-checked"),
  ).toBe("true");
  expect(host.querySelector('button[title="Request alpha"]')).not.toBeNull();
});
test("bulk review with no saved suggestions offers no approval and makes no writes", async () => {
  const count = approvals.length;
  await startReview("empty");
  expect(document.querySelector('[role="dialog"]')!.textContent).toContain(
    "No eligible suggestions to approve",
  );
  expect(
    document
      .querySelector('[role="dialog"]')!
      .querySelectorAll('input[type="checkbox"]').length,
  ).toBe(0);
  const confirm = [
    ...document
      .querySelector('[role="dialog"]')!
      .querySelectorAll<HTMLButtonElement>("button"),
  ].find((button) => button.textContent!.startsWith("Confirm 0"))!;
  expect(confirm.disabled).toBe(true);
  expect(approvals.length).toBe(count);
});

test("archived existing targets are excluded from bulk approval", async () => {
  await startReview("archived-target");
  expect(document.querySelector('[role="dialog"]')!.textContent).toContain(
    "Suggested opportunity is archived",
  );
  expect(
    document
      .querySelector('[role="dialog"]')!
      .querySelectorAll('input[type="checkbox"]').length,
  ).toBe(1);
});

test("request Decision controls persist approval/rejection and preserve status on failure", async () => {
  role = "editor"; lifecycleMode = true; bulkReviewMode = "";
  requests.forEach(item => item.status = "new");
  const {InboxPanel} = await import("../src/features/feedback/inbox-panel");
  window.location.hash = "#inbox";
  await act(async () => root.render(createElement(InboxPanel, {key:"decisions",workspace:"test-workspace",userId:"me"})));
  await settle(100);
  expect(host.querySelector("thead")!.textContent).toContain("Decision");
  expect(host.querySelector("thead")!.textContent).not.toContain("Priority");
  const reject = () => host.querySelector<HTMLButtonElement>('[aria-label="Reject Request alpha"]')!;
  failBulk = true;
  await act(async () => reject().click()); await settle();
  expect(requests[0].status).toBe("new");
  expect(host.textContent).toContain("Decision could not be saved");
  failBulk = false;
  await act(async () => reject().click()); await settle();
  expect(requests[0].status).toBe("rejected");
  expect(reject().disabled).toBe(true);
  expect(reject().closest("tr")!.textContent).toContain("Rejected");
  await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="Approve Request alpha"]')!.click()); await settle();
  expect(requests[0].status).toBe("triaged");
  expect(reject().closest("tr")!.textContent).toContain("Approved");
  expect(requests[1].status).toBe("new");
  lifecycleMode = false;
});

test("v9 Opportunities keeps bulk selection reactive and paginates the full set", async () => {
  role = "editor";
  const { OpportunityTable } =
    await import("../src/features/opportunities/opportunity-table");
  const items = Array.from({ length: 12 }, (_, i) => ({
    id: `opp-${i}`,
    name: `Opportunity ${i}`,
    status: "considering",
    priority: "medium",
    feedback_count: 1,
    created_at: "2026-11-15T00:00:00Z",
  }));
  await act(async () =>
    root.render(
      createElement(OpportunityTable, {
        items,
        workspace: "test-workspace",
        onRefresh: async () => {},
        onOpen: () => {},
      }),
    ),
  );
  await settle();
  const tableTab = [...host.querySelectorAll<HTMLElement>('[role="tab"]')].find(
    (tab) => tab.textContent === "Table",
  )!;
  expect(tableTab.getAttribute("aria-selected")).toBe("true");
  const selectPage = host.querySelector<HTMLButtonElement>(
    '[aria-label="Select page"]',
  )!;
  await act(async () => selectPage.click());
  await settle();
  expect(selectPage.getAttribute("aria-checked")).toBe("true");
  expect(
    host
      .querySelector('[aria-label="Select Opportunity 0"]')!
      .getAttribute("aria-checked"),
  ).toBe("true");
  expect(host.textContent).toContain("10 selected");
  await act(async () => selectPage.click());
  await settle();
  expect(
    host
      .querySelector('[aria-label="Select Opportunity 0"]')!
      .getAttribute("aria-checked"),
  ).toBe("false");
  const next = host.querySelector<HTMLButtonElement>(
    '[aria-label="Go to next page"]',
  )!;
  await act(async () => next.click());
  await settle();
  expect(host.querySelectorAll("tbody tr").length).toBe(2);
  expect(host.querySelector("tbody")!.textContent).toContain("Opportunity 11");
  expect(
    host.querySelector('[aria-label="Set priority for Opportunity 11"]'),
  ).not.toBeNull();
  expect(host.querySelector('[aria-label="Set status for Opportunity 11"]')).not.toBeNull();
});

test("Primer request detail keeps priority at opportunity stage and exposes supported status actions", async () => {
  role = "editor";
  failBulk = false;
  const { InboxPanel } = await import("../src/features/feedback/inbox-panel");
  await act(async () => {
    window.location.hash = "#inbox?id=alpha";
    root.render(
      createElement(InboxPanel, {
        key: "primer-detail",
        workspace: "test-workspace",
        userId: "me",
      }),
    );
  });
  await settle(100);
  expect(host.querySelector(".github-detail h1")!.textContent).toContain(
    "Request alpha",
  );
  expect(host.textContent).toContain("Linked opportunity");
  expect(host.querySelector(".issue-comment header button[aria-label=\"Support this request\"]")).not.toBeNull();
  expect(host.textContent).not.toContain("submitted this request");
  expect(host.textContent).not.toContain("Link an opportunity to enable approval.");
  expect(host.textContent).not.toContain("A request becomes Triaged only");
  expect(host.querySelector(".issue-primary-actions")!.textContent).toContain("Approve");
  expect(host.querySelector(".issue-primary-actions")!.textContent).toContain("Reject");
  expect(
    host.querySelector('select[aria-label="Request priority"]'),
  ).toBeNull();
  expect(
    [...host.querySelectorAll(".github-detail button")].some(
      (b) => b.textContent === "Reject",
    ),
  ).toBe(true);
  role = "viewer";
  await act(async () =>
    root.render(
      createElement(InboxPanel, {
        key: "primer-viewer",
        workspace: "test-workspace",
        userId: "me",
      }),
    ),
  );
  await settle(100);
  expect(
    [...host.querySelectorAll(".github-detail button")].some(
      (b) => b.textContent === "Reject",
    ),
  ).toBe(false);
  role = "editor";
});


test("Primer opportunity detail retains evidence, discussion, and review controls", async () => {
  const { OpportunitiesPage } = await import("../src/features/opportunities/opportunities-page");
  await act(async () => {
    window.location.hash = "#opportunities?id=primer-opportunity";
    root.render(createElement(OpportunitiesPage, { workspace: "test-workspace" }));
  });
  await settle(150);
  expect(host.querySelector(".github-detail h1")!.textContent).toContain(detailOpportunity.name);
  expect(host.textContent).toContain(detailOpportunity.problem);
  expect(host.textContent).not.toContain("Decision history");
  expect(host.querySelector('a[href="#inbox?status=all&id=alpha"]')).not.toBeNull();
  expect(host.querySelector('select[aria-label="Opportunity status"]')?.closest('.issue-property')?.querySelector('h2')?.textContent).toBe("Status");
  const priorityProperty = host.querySelector('select[aria-label="Opportunity priority"]')?.closest('.issue-property');
  expect(priorityProperty?.textContent).toContain("Assess priority with AI");
  expect([...host.querySelectorAll(".issue-property h2")].map(h => h.textContent)).not.toContain("Created by");
  expect(host.textContent).toContain("Add a comment");
  expect(host.querySelector('[aria-label="Decision note"]')).toBeNull();
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  const review = [...host.querySelectorAll("button")].find(b => b.textContent === "Review priority")!;
  await act(async () => review.click());
  const sheet = document.querySelector('[role="dialog"]');
  expect(sheet?.textContent).toContain("Review priority");
  expect(sheet?.textContent).toContain("PM effort estimate");
  await act(async () => sheet!.querySelector<HTMLButtonElement>('button:has(.sr-only)')!.click());
  expect(document.querySelector('[role="dialog"]')).toBeNull();

  const description = host.querySelector('article[aria-label="Opportunity description"]')!;
  expect(description.querySelector("header strong")?.textContent).toBe("Copilot");
  expect(description.textContent).toContain("Reviewers need to see what happened.");
  expect(host.textContent).not.toContain("AI analysis");
  const descriptionButton = (label: string) => [...description.querySelectorAll("button")].find(button => button.textContent === label)!;
  await act(async () => descriptionButton("Edit description").click());
  const input = description.querySelector("textarea")!;
  expect(input.value).toContain("**Evidence:**");
  await act(async () => {
    const propsKey = Object.keys(input).find(key => key.startsWith("__reactProps$"))!;
    (input as unknown as Record<string, {onChange:(event:unknown)=>void}>)[propsKey].onChange({target:{value:"**Updated description**"}});
  });
  await act(async () => descriptionButton("Preview").click());
  expect(description.querySelector(".issue-comment-preview strong")?.textContent).toBe("Updated description");
  await act(async () => description.querySelector("form")!.dispatchEvent(new browser.Event("submit", { bubbles: true, cancelable: true }) as unknown as Event));
  expect(detailOpportunity.description_markdown).toBe("**Updated description**");
  expect(description.querySelector(".analysis-markdown strong")?.textContent).toBe("Updated description");
  expect(description.textContent).not.toContain("Reviewers need to see what happened.");

});


test("request comments preview Markdown, retain failed drafts, and append a saved comment", async () => {
  role = "editor";
  const { IssueDiscussion } = await import("../src/components/issue-detail/issue-discussion");
  await act(async () => root.render(createElement(IssueDiscussion, {key:"comment-test",threadId:"alpha",workspace:"test-workspace",userId:"me",canEdit:true})));
  await settle(30);
  const input = host.querySelector("textarea")!;
  await act(async () => {
    const reactPropsKey = Object.keys(input).find(key => key.startsWith("__reactProps$"))!;
    (input as unknown as Record<string, {onChange:(e:unknown)=>void}>)[reactPropsKey].onChange({target:{value:"**Customer context**"}});
  });
  const button = (label:string) => [...host.querySelectorAll<HTMLButtonElement>("button")].find(x => x.textContent === label)!;
  await act(async () => button("Preview").click());
  expect(host.querySelector("strong")?.textContent).toBe("Customer context");
  failComment = true;
  await act(async () => button("Comment").click());
  expect(host.textContent).toContain("Comment could not be saved");
  await act(async () => button("Write").click());
  expect(host.querySelector("textarea")!.value).toBe("**Customer context**");
  failComment = false;
  await act(async () => button("Comment").click());
  expect(host.querySelector('article[aria-label="Comment"]')!.textContent).toContain("Customer context");
  expect(host.querySelector("textarea")!.value).toBe("");
  expect(commentBodies.slice(-2)).toEqual(["**Customer context**","**Customer context**"]);
});


test("manual opportunity links enable approval without an AI run and render multiple sidebar links", async () => {
  const { RequestOpportunities } = await import("../src/features/feedback/request-opportunities");
  const actions = document.createElement("div");
  const sidebar = document.createElement("div");
  document.body.append(actions,sidebar);
  let approved = 0;
  try {
    await act(async () => root.render(createElement(RequestOpportunities,{requestId:"manual",workspace:"test-workspace",canEdit:true,status:"new",actionsTarget:actions,sidebarTarget:sidebar,onConfirmed:()=>{approved++;}})));
    await settle(30);
    expect(sidebar.querySelectorAll('a[href^="#opportunities?id="]').length).toBe(2);
    expect(sidebar.textContent).toContain("Link opportunities");
    const approve = actions.querySelector("button")!;
    expect(approve.disabled).toBe(false);
    await act(async () => approve.click());
    expect(manualApproval).toEqual({expected_status:"new"});
    expect(approved).toBe(1);
    await act(async () => root.render(null));
  } finally {actions.remove();sidebar.remove();}
});


test("approval without links starts AI and preserves the request when AI is unavailable", async () => {
  const {RequestOpportunities} = await import("../src/features/feedback/request-opportunities");
  const actions = document.createElement("div"), sidebar = document.createElement("div");
  document.body.append(actions, sidebar);
  let confirmed = false;
  await act(async () => root.render(createElement(RequestOpportunities, {requestId:"ai-unavailable",workspace:"test-workspace",canEdit:true,status:"new",actionsTarget:actions,sidebarTarget:sidebar,onConfirmed:()=>{confirmed=true;}})));
  await settle(50);
  expect(actions.querySelector("button")!.disabled).toBe(false);
  await act(async () => actions.querySelector("button")!.click());
  await settle(50);
  expect(sidebar.textContent).toContain("AI is unavailable");
  expect(confirmed).toBe(false);
  expect(actions.querySelector("button")!.disabled).toBe(false);
  actions.remove();sidebar.remove();
});
