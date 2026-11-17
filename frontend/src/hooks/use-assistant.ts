import type { AssistantContext } from "@/lib/assistant-context";
import { ZodError } from "zod";
import { useEffect, useRef, useState } from "react";
import type { ComponentProps } from "react";
import type { CopilotChatView } from "@copilotkit/react-core/v2";
import { api } from "@/lib/auth-context";
import { runAssistant } from "@/lib/assistant-transport";
import {
  assistantConfigSchema,
  type AssistantConfig,
} from "@/lib/assistant-contracts";

type Messages = NonNullable<ComponentProps<typeof CopilotChatView>["messages"]>;
export type AssistantPhase =
  "idle" | "running" | "complete" | "stopped" | "error";
export function useAssistant(workspace?: string, context?: AssistantContext | null) {
  const [messages, setMessages] = useState<Messages>([]);
  const [config, setConfig] = useState<AssistantConfig | null>(null);
  const [draft, setDraft] = useState("");
  const [phase, setPhase] = useState<AssistantPhase>("idle");
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const [cost, setCost] = useState<number | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  function reset() {
    requestRef.current?.abort();
    requestRef.current = null;
    setMessages([]);
    setDraft("");
    setPhase("idle");
    setProgress("");
    setError("");
    setCost(null);
  }
  useEffect(() => {
    const abort = new AbortController();
    reset();
    setConfig(null);
    if (workspace)
      api<unknown>("/assistant/config", { signal: abort.signal }, workspace)
        .then((value) => {
          if (!abort.signal.aborted)
            setConfig(assistantConfigSchema.parse(value));
        })
        .catch((e) => {
          if (!abort.signal.aborted) {
            setError(
              e instanceof ZodError
                ? "The assistant configuration is incompatible. Restart the backend and try again."
                : e instanceof Error
                  ? e.message
                  : "Assistant configuration is unavailable.",
            );
            setPhase("error");
          }
        });
    return () => {
      abort.abort();
      requestRef.current?.abort();
      requestRef.current = null;
    };
  }, [workspace]);
  async function submit(value: string) {
    const text = value.trim();
    if (!text || requestRef.current || !config?.enabled || !workspace) return;
    if (text.length > config.max_message_chars) {
      setError(`Keep messages under ${config.max_message_chars} characters.`);
      return;
    }
    const request = new AbortController();
    requestRef.current = request;
    setPhase("running");
    setError("");
    setCost(null);
    setProgress("Thinking…");
    setDraft("");
    const responseId = crypto.randomUUID();
    setMessages((previous) => [
      ...previous,
      { id: crypto.randomUUID(), role: "user", content: text },
    ]);
    let answer = "";
    try {
      await runAssistant(
        text,
        workspace,
        request.signal,
        (event) => {
          if (request.signal.aborted || requestRef.current !== request) return;
          if (event.type === "status") setProgress(event.message);
          if (event.type === "text" && event.text) {
            answer += (answer ? "\n\n" : "") + event.text;
            setMessages((previous) => [
              ...previous.filter((item) => item.id !== responseId),
              { id: responseId, role: "assistant", content: answer },
            ]);
          }
          if (event.type === "done") setCost(event.cost_usd ?? null);
        },
        config,
        context ? { kind: context.kind, id: context.id } : undefined,
      );
      if (requestRef.current === request) {
        setPhase("complete");
        setProgress("");
      }
    } catch (e) {
      if (requestRef.current === request) {
        setPhase(request.signal.aborted ? "stopped" : "error");
        setProgress("");
        if (!request.signal.aborted)
          setError(
            e instanceof ZodError
              ? "The assistant returned an unexpected response. Please try a new chat."
              : e instanceof Error
                ? e.message
                : "The assistant request failed.",
          );
      }
    } finally {
      if (requestRef.current === request) requestRef.current = null;
    }
  }
  return {
    messages,
    context,
    config,
    draft,
    setDraft,
    phase,
    progress,
    error,
    cost,
    reset,
    submit,
    stop: () => requestRef.current?.abort(),
    busy: phase === "running",
  };
}
export type AssistantController = ReturnType<typeof useAssistant>;
