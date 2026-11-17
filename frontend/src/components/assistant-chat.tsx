import { useEffect, useState } from "react";
import { useAssistantContext } from "@/lib/assistant-context";
import { useAuth } from "@/lib/auth-context";
import { useAssistant } from "@/hooks/use-assistant";
import { AssistantChatView } from "./assistant-chat-view";

export default function AssistantChat() {
  const { active } = useAuth();
  const selected = useAssistantContext();
  const [route, setRoute] = useState(() => window.location.hash);
  useEffect(() => {
    const update = () => setRoute(window.location.hash);
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  const [pageName, query] = route.slice(1).split("?");
  const pages = [
    "inbox",
    "opportunities",
    "tasks",
    "updates",
    "feedback",
    "settings",
    "home",
  ];
  const page = pages.includes(pageName) ? pageName : "home";
  const params = new URLSearchParams(query);
  const recordId = params.get("id");
  const kind = {
    inbox: "feedback",
    opportunities: "opportunity",
    tasks: "task",
  }[page];
  const context =
    kind && recordId && active
      ? {
          workspace: active.workspace_slug,
          kind: kind as "feedback" | "opportunity" | "task",
          id: recordId,
          label: selected?.id === recordId ? selected.label : page,
        }
      : null;
  const assistant = useAssistant(active?.workspace_slug, context, {
    page,
    search: params.get("search") || "",
    status: params.get("status") || "all",
  });
  return (
    <AssistantChatView
      key={active?.workspace_slug}
      assistant={assistant}
      workspaceName={active?.workspace_name}
    />
  );
}
