import { useState } from "react";
import {
  AbstractAgent,
  CopilotKitProvider,
  CopilotChatConfigurationProvider,
  CopilotChatView,
} from "@copilotkit/react-core/v2";
import {
  ArrowUpRight,
  Bot,
  Check,
  CircleAlert,
  Ellipsis,
  Layers,
  Loader2,
  Plus,
  Search,
} from "lucide-react";
import { APP } from "@/lib/app-config";
import type { AssistantController } from "@/hooks/use-assistant";
import { Button } from "@/components/ui/button";
import { AssistantComposer } from "./assistant-composer";
import "@copilotkit/react-core/v2/styles.css";
import "./assistant-chat.css";

// CopilotKit renders the transcript. The app controller owns all assistant requests.
class TranscriptAgent extends AbstractAgent {
  run(): never {
    throw new Error("Assistant requests must use the app assistant controller.");
  }
}

export function AssistantChatView({
  assistant,
  workspaceName,
}: {
  assistant: AssistantController;
  workspaceName?: string;
}) {
  const [agents] = useState(() => ({ default: new TranscriptAgent() }));
  const [details, setDetails] = useState(false);
  const empty = assistant.messages.length === 0;
  return (
    <div className="assistant-surface">
      <header className="assistant-header">
        <div className="assistant-heading">
          <Bot aria-hidden="true" />
          <h2>{APP.assistant.title}</h2>
        </div>
        <div className="flex items-center gap-0.5">
          <Button
            variant="ghost"
            size="icon"
            className="assistant-header-action"
            aria-label="New chat"
            title="New chat"
            onClick={assistant.reset}
          >
            <Plus />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="assistant-header-action"
            aria-label="Assistant details"
            title="Assistant details"
            aria-expanded={details}
            aria-controls="assistant-details"
            onClick={() => setDetails(!details)}
          >
            <Ellipsis />
          </Button>
        </div>
      </header>
      <div className="assistant-context" title={workspaceName}>
        <Layers aria-hidden="true" />
        <span>{workspaceName}</span>
        <span className="assistant-context-divider">/</span>
        <span title={assistant.context?.label}>{assistant.context?.label || "Workspace"}</span>
      </div>
      {details && (
        <div id="assistant-details" className="assistant-details">
          <p>{APP.assistant.contextNote}</p>
          <p>
            Available tools:{" "}
            {assistant.config?.capabilities.join(", ") || "Not connected"}.
          </p>
          <p>Enter sends. Shift+Enter inserts a new line.</p>
        </div>
      )}
      {assistant.config?.independent_requests && (
        <p className="px-3 py-1 text-xs text-muted-foreground">
          Uses the selected item. Each request starts fresh; earlier messages are not sent.
        </p>
      )}
      <CopilotKitProvider
        selfManagedAgents={agents}
        enableInspector={false}
        showIntelligenceIndicator={false}
      >
        <CopilotChatConfigurationProvider>
          <CopilotChatView
            className="assistant-chat"
            messages={assistant.messages}
            welcomeScreen={false}
            isRunning={assistant.busy}
            autoScroll="pin-to-bottom"
            scrollView={{ className: "assistant-transcript" }}
            messageView={{
              className: "assistant-messages",
              messageFeedback: false,
              assistantMessage: {
                className: "assistant-answer",
                toolbarVisible: true,
              },
              userMessage: { className: "assistant-question" },
            }}
          >
            {({ scrollView }) => (
              <div className="assistant-chat-layout">
                {empty ? (
                  <div className="assistant-welcome">
                    <div className="assistant-welcome-icon">
                      <Bot />
                    </div>
                    <h3>{APP.assistant.welcomeTitle}</h3>
                    <p>{APP.assistant.welcomeDescription}</p>
                    <div className="assistant-starters">
                      {APP.assistant.starterPrompts.map((item) => (
                        <Button
                          key={item.id}
                          variant="outline"
                          className="assistant-starter"
                          disabled={!assistant.config?.enabled}
                          onClick={() => void assistant.submit(item.prompt)}
                        >
                          <Search aria-hidden="true" />
                          <span>
                            <strong>{item.label}</strong>
                            <small>{item.description}</small>
                          </span>
                          <ArrowUpRight aria-hidden="true" />
                        </Button>
                      ))}
                    </div>
                  </div>
                ) : (
                  scrollView
                )}
                {(assistant.busy || assistant.phase !== "idle") && (
                  <div className="assistant-run-status" role="status">
                    {assistant.busy ? (
                      <Loader2 className="motion-safe:animate-spin" />
                    ) : assistant.phase === "complete" ? (
                      <Check />
                    ) : (
                      <CircleAlert />
                    )}
                    <span>
                      {assistant.busy
                        ? assistant.progress
                        : assistant.phase === "complete"
                          ? "Completed"
                          : assistant.phase === "stopped"
                            ? "Stopped"
                            : "Request failed"}
                    </span>
                    {assistant.cost !== null && (
                      <span className="ml-auto tabular-nums">
                        ${assistant.cost.toFixed(4)}
                      </span>
                    )}
                  </div>
                )}
                {assistant.error && (
                  <div className="assistant-error" role="alert">
                    {assistant.error}
                  </div>
                )}
                {assistant.config && !assistant.config.enabled && (
                  <div className="rounded-lg border bg-muted/40 px-3 py-2 text-sm text-muted-foreground" role="status">
                    Assistant unavailable in this preview.
                  </div>
                )}
                <AssistantComposer assistant={assistant} />
              </div>
            )}
          </CopilotChatView>
        </CopilotChatConfigurationProvider>
      </CopilotKitProvider>
    </div>
  );
}
