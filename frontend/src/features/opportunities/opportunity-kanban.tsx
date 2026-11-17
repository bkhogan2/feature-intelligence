import { useRef, useState, type ReactNode } from "react";
import { KeyboardSensor, MouseSensor, TouchSensor, useSensor, useSensors } from "@dnd-kit/core";
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable";
import {
  KanbanBoard, KanbanCard, KanbanCards, KanbanHeader, KanbanProvider,
} from "@/components/ui/kanban";
import { mergeVisible } from "./opportunity-board-model";

export type BoardOpportunity = {
  id: string;
  name: string;
  problem?: string;
  status: string;
  priority: string | null;
  feedback_count: number;
  created_at: string;
  secondaryLabel?: string;
};
type Card = BoardOpportunity & { column: string };
const opportunityColumns = [
  { id: "considering", name: "Considering" },
  { id: "planned", name: "Planned" },
  { id: "in_progress", name: "In progress" },
  { id: "shipped", name: "Shipped" },
  { id: "not_pursuing", name: "Not pursuing" },
];

export function OpportunityKanban({
  items, allItems, onCommit, onOpen, view,
  disabled = false,
  boardColumns = opportunityColumns,
  instructions = "Drag cards to move them. Use Space and the arrow keys to move a focused card.",
  evidenceLabel = "requests",
  emptyLabel = "No items.",
  readOnlyInstructions = "Open a card to view its details.",
  dropLabel = "Drop a card here",
  renderCardMetadata,
}: {
  items: BoardOpportunity[];
  allItems: BoardOpportunity[];
  onCommit: (items: BoardOpportunity[]) => Promise<boolean>;
  onOpen: (id: string) => void;
  view: "board" | "list";
  disabled?: boolean;
  boardColumns?: { id: string; name: string }[];
  instructions?: string;
  evidenceLabel?: string;
  emptyLabel?: string;
  readOnlyInstructions?: string;
  dropLabel?: string;
  renderCardMetadata?: (item: BoardOpportunity) => ReactNode;
}) {
  const [preview, setPreview] = useState<Card[] | null>(null);
  const pending = useRef<Card[] | null>(null);
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const cards = preview ?? items.map((item) => ({ ...item, column: item.status }));
  const extraStatuses = new Set(items.map((item) => item.status));
  for (const column of boardColumns) extraStatuses.delete(column.id);
  const columns = [
    ...boardColumns,
    ...Array.from(extraStatuses, (id) => ({ id, name: id })),
  ];

  function clearPreview() {
    pending.current = null;
    setPreview(null);
  }

  function content(item: Card) {
    return (
      <>
        <button type="button" className="text-left font-medium hover:underline"
          onMouseDown={(event) => event.stopPropagation()}
          onTouchStart={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
          onClick={() => onOpen(item.id)}>
          {item.name}
        </button>
        {renderCardMetadata?.(item) ?? (
          <p className="text-xs text-muted-foreground">
            {item.secondaryLabel || item.priority || "Unprioritized"} · {item.feedback_count} {evidenceLabel}
          </p>
        )}
      </>
    );
  }

  if (view === "list") {
    return (
      <div className="space-y-4">
        {columns.map(({ id, name }) => {
          const group = cards.filter((card) => card.column === id);
          return (
            <section key={id} className="overflow-hidden rounded-md border">
              <h2 className="border-b bg-muted px-4 py-2 text-sm font-medium">{name} ({group.length})</h2>
              {group.length ? (
                <ul className="divide-y">
                  {group.map((item) => <li key={item.id} className="px-4 py-2 text-sm">{content(item)}</li>)}
                </ul>
              ) : <p className="px-4 py-2 text-sm text-muted-foreground">{emptyLabel}</p>}
            </section>
          );
        })}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto pb-3">
      <p className="mb-3 text-xs text-muted-foreground">{disabled ? readOnlyInstructions : instructions}</p>
      <KanbanProvider
        className="min-w-max auto-cols-[17rem]"
        columns={columns}
        data={cards}
        sensors={sensors}
        onDataChange={(next) => { pending.current = next; setPreview(next); }}
        onDragCancel={clearPreview}
        onDragEnd={async ({ active, over }) => {
          try {
            if (disabled || !over) return;
            const current = pending.current ?? cards;
            const destination = current.find((card) => card.id === over.id)?.column
              ?? columns.find((column) => column.id === over.id)?.id;
            if (!destination) return;
            if (!pending.current && current.find((card) => card.id === active.id)?.column === destination) return;
            const moved = current.map(({ column, ...item }) => ({
              ...item, status: item.id === active.id ? destination : column,
            }));
            await onCommit(mergeVisible(allItems, moved));
          } finally {
            clearPreview();
          }
        }}
      >
        {({ id, name }) => (
          <KanbanBoard key={id} id={id} className="min-h-48">
            <KanbanHeader>{name}</KanbanHeader>
            <KanbanCards<Card> id={id} className="p-2">
              {(item) => (
                <KanbanCard key={item.id} {...item} disabled={disabled}>
                  {content(item)}
                </KanbanCard>
              )}
            </KanbanCards>
            {!cards.some((card) => card.column === id) && (
              <p className="p-3 text-sm text-muted-foreground">{disabled ? emptyLabel : dropLabel}</p>
            )}
          </KanbanBoard>
        )}
      </KanbanProvider>
    </div>
  );
}
