import { useEffect, useRef } from "react";
import { ArrowUp, ChevronDown, Cpu, ShieldCheck, Square } from "lucide-react";
import { APP } from "@/lib/app-config";
import { modelDisplayName } from "@/lib/assistant-contracts";
import type { AssistantController } from "@/hooks/use-assistant";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";

export function AssistantComposer({
  assistant,
}: {
  assistant: AssistantController;
}) {
  const input = useRef<HTMLTextAreaElement>(null);
  const { config, draft, setDraft, busy, submit, stop } = assistant;
  const enabled = config?.enabled === true;
  useEffect(() => {
    if (!input.current) return;
    input.current.style.height = "0px";
    input.current.style.height = `${Math.min(144, Math.max(44, input.current.scrollHeight))}px`;
  }, [draft]);
  return (
    <div className="assistant-compose-area">
      <form
        className="assistant-composer"
        onSubmit={(event) => {
          event.preventDefault();
          void submit(draft);
        }}
      >
        <Textarea
          ref={input}
          rows={2}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          maxLength={config?.max_message_chars}
          disabled={!enabled}
          aria-label="Message assistant"
          placeholder={
            enabled
              ? APP.assistant.placeholder
              : config
                ? "Agent setup required"
                : "Connecting…"
          }
          className="assistant-textarea"
          onKeyDown={(event) => {
            if (
              event.key === "Enter" &&
              !event.shiftKey &&
              !event.nativeEvent.isComposing
            ) {
              event.preventDefault();
              if (!busy) void submit(draft);
            }
          }}
        />
        <div className="assistant-composer-toolbar">
          <span
            className="assistant-mode"
            title="The assistant can search records and navigate. It cannot modify data."
          >
            <ShieldCheck aria-hidden="true" />
            {APP.assistant.modeLabel}
          </span>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                className="assistant-model-button"
                aria-label="Model and usage details"
              >
                <Cpu aria-hidden="true" />
                <span>
                  {config ? modelDisplayName(config.model) : "Connecting"}
                </span>
                <ChevronDown aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-64">
              <DropdownMenuLabel>Model & limits</DropdownMenuLabel>
              <div className="space-y-2 px-2 py-1.5 text-xs text-muted-foreground">
                <p className="break-all font-medium text-foreground">
                  {config?.model || "Not connected"}
                </p>
                {config && (
                  <>
                    <p>
                      {config.max_turns} turns · {config.max_output_tokens}{" "}
                      output tokens
                    </p>
                    <p>
                      $
                      {config.max_budget_usd.toLocaleString("en-US", {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 4,
                      })}{" "}
                      SDK budget per run
                    </p>
                    <p>
                      {config.max_message_chars.toLocaleString()} characters per
                      message
                    </p>
                  </>
                )}
                {assistant.cost !== null && (
                  <p>Last run: ${assistant.cost.toFixed(4)}</p>
                )}
              </div>
              <DropdownMenuSeparator />
              <p className="px-2 py-1.5 text-xs text-muted-foreground">
                Model and limits are managed by your server. The SDK budget is
                checked between calls.
              </p>
            </DropdownMenuContent>
          </DropdownMenu>
          {busy ? (
            <Button
              type="button"
              variant="secondary"
              size="icon"
              className="assistant-send"
              aria-label="Stop response"
              title="Stop response"
              onClick={stop}
            >
              <Square className="size-3 fill-current" />
            </Button>
          ) : (
            <Button
              type="submit"
              size="icon"
              className="assistant-send"
              aria-label="Send message"
              title="Send message"
              disabled={!enabled || !draft.trim()}
            >
              <ArrowUp className="size-4" />
            </Button>
          )}
        </div>
      </form>
      <div className="assistant-compose-note">
        <span>{APP.assistant.notice} · Current conversation</span>
        <span className="assistant-key-hint">↵ Send</span>
      </div>
    </div>
  );
}
