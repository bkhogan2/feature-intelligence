// Development-only visual fixture. Never calls the backend or a model provider.
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { AssistantChatView } from "../../src/components/assistant-chat-view";
import type {
  AssistantController,
  AssistantPhase,
} from "../../src/hooks/use-assistant";
import { Button } from "../../src/components/ui/button";
import { TooltipProvider } from "../../src/components/ui/tooltip";
import "../../src/styles.css";
import "../../src/components/app-shell.css";

const fixtureMessages: AssistantController["messages"] = [
  {
    id: "user",
    role: "user",
    content: "Find the demo records in this workspace and show them to me.",
  },
  {
    id: "assistant",
    role: "assistant",
    content:
      "I found **3 demo records** and opened the matching Records view:\n\n- Website redesign — Planning\n- Onboarding checklist — In progress\n- Monthly report — Draft\n\nNo records were changed.",
  },
];
function Fixture() {
  const [messages, setMessages] = useState(fixtureMessages);
  const [draft, setDraft] = useState("");
  const [phase, setPhase] = useState<AssistantPhase>("complete");
  const [width, setWidth] = useState(420);
  const config: NonNullable<AssistantController["config"]> = {
    enabled: true,
    model: "claude-haiku-5-5",
    mode: "read-only",
    synthetic_only: true,
    independent_requests: true,
    max_turns: 4,
    max_budget_usd: 0.05,
    max_output_tokens: 768,
    max_message_chars: 1000,
    request_timeout_seconds: 90,
    navigation_timeout_ms: 8000,
    capabilities: ["search_records", "open_records"],
  };
  const assistant: AssistantController = {
    messages,
    config,
    draft,
    setDraft,
    phase,
    progress: "Searching synthetic records…",
    error:
      phase === "error"
        ? "Offline fixture: connection interrupted. You can retry this request."
        : "",
    cost: phase === "complete" ? 0.0003 : null,
    busy: phase === "running",
    reset: () => {
      setMessages([]);
      setDraft("");
      setPhase("idle");
    },
    stop: () => setPhase("stopped"),
    submit: async (text) => {
      if (text.trim()) {
        setMessages([
          ...fixtureMessages,
          { id: crypto.randomUUID(), role: "user", content: text },
          {
            id: crypto.randomUUID(),
            role: "assistant",
            content: "Offline visual fixture. No model request was made.",
          },
        ]);
        setDraft("");
        setPhase("complete");
      }
    },
  };
  return (
    <TooltipProvider>
      <div className="min-h-screen bg-muted p-4 text-foreground">
        <div className="mb-4 flex flex-wrap items-center gap-2 text-xs">
          <strong>Offline visual fixture · no model calls</strong>
          <Button
            size="sm"
            onClick={() => document.documentElement.classList.toggle("dark")}
          >
            Toggle dark
          </Button>
          <Button size="sm" onClick={() => setWidth(width === 420 ? 280 : 420)}>
            Toggle narrow
          </Button>
          <Button
            size="sm"
            onClick={() => {
              setMessages(fixtureMessages);
              setPhase("complete");
            }}
          >
            Completed
          </Button>
          <Button size="sm" onClick={() => setPhase("running")}>
            Running
          </Button>
          <Button size="sm" onClick={() => setPhase("error")}>
            Error
          </Button>
        </div>
        <div
          className="navigation-sidebar flex overflow-hidden rounded-xl border shadow-sm"
          style={{
            width: `min(${width}px, 100%)`,
            height: "calc(100dvh - 100px)",
            minHeight: 360,
          }}
        >
          <AssistantChatView
            assistant={assistant}
            workspaceName="Demo workspace"
          />
        </div>
      </div>
    </TooltipProvider>
  );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
