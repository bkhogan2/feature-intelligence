import { z } from "zod";

export const assistantConfigSchema = z.object({
  enabled: z.boolean(),
  model: z.string().min(1).max(128),
  mode: z.literal("read-only"),
  synthetic_only: z.boolean(),
  independent_requests: z.literal(true),
  max_turns: z.number().int().positive(),
  max_budget_usd: z.number().finite().positive(),
  max_output_tokens: z.number().int().positive(),
  max_message_chars: z.number().int().min(100).max(4000),
  request_timeout_seconds: z.number().int().min(15).max(180),
  navigation_timeout_ms: z.number().int().min(1000).max(30000),
  capabilities: z.array(z.enum(["search_records", "open_records", "search_feedback", "get_feedback", "search_opportunities", "get_opportunity"])),
});
export type AssistantConfig = z.infer<typeof assistantConfigSchema>;
export const assistantEventSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("start"), run_id: z.string().min(1).max(100) }),
  z.object({ type: z.literal("status"), message: z.string().max(1000) }),
  z.object({ type: z.literal("text"), text: z.string().max(32000) }),
  z.object({
    type: z.literal("action"),
    name: z.literal("open_records"),
    query: z.string().max(120),
    run_id: z.string().min(1).max(100),
    action_id: z.string().min(1).max(100),
  }),
  z.object({
    type: z.literal("done"),
    cost_usd: z.number().finite().nonnegative().nullable().optional(),
    error: z.boolean(),
    turns: z.number().int().nonnegative().optional(),
  }),
  z.object({ type: z.literal("error"), message: z.string().max(1000) }),
]);
export type AssistantEvent = z.infer<typeof assistantEventSchema>;

// A shared stream decoder keeps malformed/unbounded events out of UI actions.
export async function* readAssistantEvents(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal,
) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const cancel = () => {
    void reader.cancel().catch(() => {});
  };
  signal.addEventListener("abort", cancel, { once: true });
  let pending = "";
  try {
    while (!signal.aborted) {
      const { value, done } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      let boundary: number;
      while ((boundary = pending.indexOf("\n")) !== -1) {
        const line = pending.slice(0, boundary);
        pending = pending.slice(boundary + 1);
        if (line.length > 65536)
          throw new Error("Assistant response exceeded the event limit.");
        if (line.trim() && !signal.aborted)
          yield assistantEventSchema.parse(JSON.parse(line));
      }
      if (pending.length > 65536)
        throw new Error("Assistant response exceeded the event limit.");
      if (done) break;
    }
    if (!signal.aborted && pending.trim())
      yield assistantEventSchema.parse(JSON.parse(pending));
  } finally {
    signal.removeEventListener("abort", cancel);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
export function modelDisplayName(id: string) {
  const known = /^claude-(haiku|sonnet|opus)-(\d+)-(\d+)$/.exec(id);
  return known
    ? `${known[1][0].toUpperCase()}${known[1].slice(1)} ${known[2]}.${known[3]}`
    : id;
}
