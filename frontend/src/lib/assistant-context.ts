import { useEffect, useSyncExternalStore } from "react";
export type AssistantContext = {
  kind: "feedback" | "opportunity" | "task";
  id: string;
  label: string;
  workspace: string;
};
let current: AssistantContext | null = null;
const listeners = new Set<() => void>();
function publish(value: AssistantContext | null) {
  current = value;
  listeners.forEach((listener) => listener());
}
export function useSelectedAssistantContext(
  workspace: string,
  kind: AssistantContext["kind"],
  id?: string | null,
  label?: string,
) {
  useEffect(() => {
    publish(id ? { workspace, kind, id, label: label || kind } : null);
    return () => publish(null);
  }, [workspace, kind, id, label]);
}
export function useAssistantContext() {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    () => current,
  );
}
