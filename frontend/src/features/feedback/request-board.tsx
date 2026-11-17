// Adapts requests to the shared Kibo UI board.
import { useState } from "react";
import { OpportunityKanban, type BoardOpportunity } from "../opportunities/opportunity-kanban";
import type { RequestItem, RequestPatch } from "./request-table";
const columns = [
  { id: "unprioritized", name: "Unprioritized" },
  { id: "high", name: "High" },
  { id: "medium", name: "Medium" },
  { id: "low", name: "Low" },
];
export function RequestBoard({ items, disabled, onOpen, onChange, view = "board" }: {
  items: RequestItem[]; disabled: boolean; onOpen: (id: string) => void;
  onChange: (ids: string[], patch: RequestPatch) => Promise<void>; view?: "board" | "list";
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const cards: BoardOpportunity[] = items.map(item => ({
    id: item.id, name: item.title, problem: item.description,
    secondaryLabel: item.status === "triaged" ? "Approved" : item.status === "needs_clarification" ? "Needs clarification" : item.status.charAt(0).toUpperCase() + item.status.slice(1),
    status: item.priority || "unprioritized", priority: item.priority ?? null,
    feedback_count: item.support_count, created_at: item.created_at,
  }));
  return <div className="space-y-3">
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {saving && <p role="status">Saving priority…</p>}
    <OpportunityKanban items={cards} allItems={cards} view={view} disabled={disabled || saving}
      evidenceLabel="supporters" boardColumns={columns} emptyLabel="No requests here." onOpen={onOpen}
      instructions="Drag between columns to change priority. Triage status stays unchanged. Keyboard: Space to pick up, arrows to move, Space to drop, Escape to cancel."
      onCommit={async next => {
        const changes = next.filter(item => cards.find(original => original.id === item.id)?.status !== item.status);
        if (!changes.length || disabled || saving) return true;
        setSaving(true); setError("");
        try {
          // A drag moves one card. Group by target priority for an atomic API update.
          for (const column of columns) {
            const ids = changes.filter(item => item.status === column.id).map(item => item.id);
            if (ids.length) await onChange(ids, { priority: column.id === "unprioritized" ? null : column.id as "high" | "medium" | "low" });
          }
          return true;
        } catch (err) { setError(`Could not save priority: ${(err as Error).message}`); return false; }
        finally { setSaving(false); }
      }} />
  </div>;
}
