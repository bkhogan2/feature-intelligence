import { useAssistantContext } from "@/lib/assistant-context";
import { useAuth } from "@/lib/auth-context";
import { useAssistant } from "@/hooks/use-assistant";
import { AssistantChatView } from "./assistant-chat-view";

export default function AssistantChat() {
  const { active } = useAuth();
  const selected = useAssistantContext();
  const context = selected?.workspace === active?.workspace_slug ? selected : null;
  const assistant = useAssistant(active?.workspace_slug, context);
  return (
    <AssistantChatView
      assistant={assistant}
      workspaceName={active?.workspace_name}
    />
  );
}
