import { describe, expect, test } from "bun:test";
import {
  assistantConfigSchema,
  readAssistantEvents,
  modelDisplayName,
} from "../src/lib/assistant-contracts";
import {
  clampPanelWidth,
  savedPanelWidth,
  panelBounds,
} from "../src/lib/panel-sizing";
import { APP } from "../src/lib/app-config";

const config = {
  enabled: true,
  model: "claude-haiku-5-5",
  mode: "read-only",
  synthetic_only: false,
  independent_requests: true,
  max_turns: 3,
  max_budget_usd: 0.02,
  max_output_tokens: 512,
  max_message_chars: 600,
  request_timeout_seconds: 45,
  navigation_timeout_ms: 4000,
  capabilities: ["search_feedback", "get_feedback", "search_opportunities", "get_opportunity"],
};
function body(chunks: Uint8Array[]) {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(chunk));
      controller.close();
    },
  });
}
async function events(chunks: Uint8Array[]) {
  const result = [];
  for await (const event of readAssistantEvents(
    body(chunks),
    new AbortController().signal,
  ))
    result.push(event);
  return result;
}
describe("assistant contract boundaries", () => {
  test("reads actual server policy instead of duplicated UI limits", () => {
    const parsed = assistantConfigSchema.parse(config);
    expect(parsed.max_turns).toBe(3);
    expect(parsed.max_budget_usd).toBe(0.02);
    expect(parsed.max_message_chars).toBe(600);
    expect(
      assistantConfigSchema.safeParse({ ...config, mode: "write-anything" })
        .success,
    ).toBe(false);
    expect(
      assistantConfigSchema.safeParse({ ...config, max_budget_usd: Infinity })
        .success,
    ).toBe(false);
  });
  test("handles NDJSON across chunk and UTF-8 boundaries, including a final line without newline", async () => {
    const bytes = new TextEncoder().encode(
      JSON.stringify({ type: "text", text: "Found résumé ✓" }) +
        "\n" +
        JSON.stringify({ type: "done", cost_usd: 0.0003, error: false }),
    );
    const parsed = await events(
      Array.from(bytes, (byte) => new Uint8Array([byte])),
    );
    expect(parsed).toEqual([
      { type: "text", text: "Found résumé ✓" },
      { type: "done", cost_usd: 0.0003, error: false },
    ]);
  });
  test("rejects unknown UI commands and malformed / oversized events", async () => {
    const encode = (value: unknown) => [
      new TextEncoder().encode(JSON.stringify(value)),
    ];
    await expect(
      events(
        encode({
          type: "action",
          name: "delete_records",
          query: "",
          run_id: "run",
          action_id: "action",
        }),
      ),
    ).rejects.toThrow();
    await expect(
      events([new TextEncoder().encode("x".repeat(65537))]),
    ).rejects.toThrow("event limit");
    await expect(
      events([new TextEncoder().encode("not json\n")]),
    ).rejects.toThrow();
  });
  test("cancelled streams cannot deliver a queued frontend action", async () => {
    const controller = new AbortController();
    controller.abort();
    const parsed = [];
    for await (const event of readAssistantEvents(
      body([
        new TextEncoder().encode(
          JSON.stringify({
            type: "action",
            name: "open_records",
            query: "demo",
            run_id: "run",
            action_id: "action",
          }),
        ),
      ]),
      controller.signal,
    ))
      parsed.push(event);
    expect(parsed).toHaveLength(0);
  });
  test("model labels remain readable without pretending an unknown model is supported", () => {
    expect(modelDisplayName("claude-haiku-5-5")).toBe("Haiku 5.5");
    expect(modelDisplayName("custom-provider-model")).toBe(
      "custom-provider-model",
    );
  });
});
describe("reusable panel sizing", () => {
  const policy = APP.assistant.panel;
  test("invalid persisted sizes recover; restored widths fit the current viewport", () => {
    expect(savedPanelWidth("NaN", policy, 1400)).toBe(policy.defaultWidth);
    expect(savedPanelWidth("-1", policy, 1400)).toBe(policy.defaultWidth);
    expect(savedPanelWidth("99999", policy, 1000)).toBe(600);
    expect(clampPanelWidth(Infinity, policy, 1400)).toBe(policy.defaultWidth);
    expect(panelBounds(policy, 1000).max).toBe(600);
    expect(clampPanelWidth(500, policy, 500)).toBe(300);
  });
  test("one navigation registry drives page/module relationships", () => {
    expect(new Set(APP.pages.map((page) => page.id)).size).toBe(
      APP.pages.length,
    );
    for (const page of APP.pages)
      expect(APP.modules.some((module) => module.id === page.module)).toBe(
        true,
      );
  });
});

test("namespaced preferences tolerate blocked browser storage", async () => {
  const { readSetting, writeSetting, storageKey } =
    await import("../src/lib/app-storage");
  const previous = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    get() {
      throw new Error("Storage unavailable");
    },
  });
  try {
    expect(storageKey("assistant-width")).toBe(`${APP.id}:assistant-width`);
    expect(readSetting("palette", "slate")).toBe("slate");
    expect(() => writeSetting("palette", "blue")).not.toThrow();
  } finally {
    if (previous) Object.defineProperty(globalThis, "localStorage", previous);
    else Reflect.deleteProperty(globalThis, "localStorage");
  }
});

test("aborting an open stream releases a pending read", async () => {
  const controller = new AbortController();
  let cancelled = false;
  const stream = new ReadableStream<Uint8Array>({
    cancel() {
      cancelled = true;
    },
  });
  const iterator = readAssistantEvents(stream, controller.signal);
  const pending = iterator.next();
  controller.abort();
  expect(await pending).toEqual({ value: undefined, done: true });
  expect(cancelled).toBe(true);
});
