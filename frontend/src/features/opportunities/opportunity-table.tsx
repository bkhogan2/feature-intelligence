import {
  dataTableFeatures,
  type DataTableFeatures,
} from "@/lib/data-table-features";
import { DataTableToolbar } from "@/registry/bases/radix/components/data-table/data-table-toolbar";
import { DataTableSortMenu } from "@/registry/bases/radix/components/data-table/data-table-sort-menu";
import { DataTableColumnHeader } from "@/registry/bases/radix/components/data-table/data-table-column-header";
import { ViewSwitch } from "@/components/data-table/view-switch";
import { useMemo, useState } from "react";
import {
  useTable,
  Subscribe,
  type ColumnDef,
  type Column,
  type SortingState,
  type ColumnFiltersState,
} from "@tanstack/react-table";
import {
  Archive,
  ArrowUp,
  ArrowDown,
  ArrowRight,
  ChevronsUpDown,
  PlusCircle,
  SlidersHorizontal,
  ArrowDownUp,
  EyeOff,
  CheckCircle2,
  Circle,
  CircleDashed,
  Timer,
  XCircle,
  X,
} from "lucide-react";
import {
  lifecycleLabels,
  priorities,
  saveManualPriority,
  saveOpportunityStatus,
} from "./opportunity-edits";
import type { PriorityFields } from "./priority-section";
import { BatchPriority } from "./batch-priority";
import { OpportunityKanban } from "./opportunity-kanban";
import { Checkbox } from "@/components/ui/checkbox";
import { api, useAuth } from "@/lib/auth-context";
import { DataTable } from "@/registry/bases/radix/components/data-table/data-table";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuCheckboxItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
type Item = {
  id: string;
  name: string;
  problem?: string;
  status: string;
  priority: string | null;
  feedback_count: number;
  created_at: string;
  archived?: boolean;
  board_order?: number | null;
};
const labels: Record<string, string> = {
  name: "Title",
  status: "Status",
  priority: "Priority",
  feedback_count: "Evidence",
  created_at: "Created at",
  high: "High",
  medium: "Medium",
  low: "Low",
  unprioritized: "Unprioritized",
  archived: "Archived",
  ...lifecycleLabels,
};
const icons: Record<string, typeof Circle> = {
  high: ArrowUp,
  medium: ArrowRight,
  low: ArrowDown,
  unprioritized: CircleDashed,
  archived: Archive,
  considering: Circle,
  planned: CircleDashed,
  in_progress: Timer,
  shipped: CheckCircle2,
  not_pursuing: XCircle,
};
function Pill({ value }: { value: string }) {
  const Icon = icons[value] || Circle;
  return (
    <span className={`opportunity-value opportunity-value-${value}`}>
      <Icon className="size-3.5" />
      {labels[value] || value}
    </span>
  );
}
function ValuePicker<T extends string>({
  label,
  value,
  options,
  disabled,
  onSelect,
}: {
  label: string;
  value: string;
  options: readonly T[];
  disabled: boolean;
  onSelect: (value: T) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          aria-label={label}
          className="rounded-full focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50"
        >
          <Pill value={value} />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        {options.map((option) => (
          <DropdownMenuItem
            key={option}
            disabled={option === value}
            onSelect={() => onSelect(option)}
          >
            <Pill value={option} />
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
export function OpportunityTable({
  items,
  workspace,
  onOpen,
  onRefresh,
}: {
  items: Item[];
  workspace: string;
  onRefresh: () => Promise<void>;
  onOpen: (id: string) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [mutationError, setMutationError] = useState("");
  const { active } = useAuth();
  const canEdit =
    active?.workspace_slug === workspace &&
    (active.role === "admin" || active.role === "editor");

  const [notice, setNotice] = useState("");
  const [rowSelection, setRowSelection] = useState({});
  const localItems = useMemo(
    () =>
      [...items].sort(
        (a, b) =>
          (a.board_order ?? Number.MAX_SAFE_INTEGER) -
          (b.board_order ?? Number.MAX_SAFE_INTEGER),
      ),
    [items],
  );
  const [filters, setFilters] = useState<ColumnFiltersState>([]);
  const statusValues = filters.find((filter) => filter.id === "status")
    ?.value as string[] | undefined;
  const showArchived = statusValues?.includes("archived") ?? false;
  const activeItems = useMemo(
    () => localItems.filter((item) => Boolean(item.archived) === showArchived),
    [localItems, showArchived],
  );
  const [view, setView] = useState<"board" | "list" | "table">("table");
  const [sorting, setSorting] = useState<SortingState>([]);

  async function setPriority(id: string, priority: "high" | "medium" | "low") {
    if (saving || !canEdit) return;
    setSaving(true);
    setMutationError("");
    try {
      const detail = await api<PriorityFields>(
        `/opportunities/${id}`,
        {},
        workspace,
      );
      await saveManualPriority(workspace, detail, priority);
      await onRefresh();
      setNotice("Priority saved. Lifecycle status unchanged.");
    } catch (error) {
      setMutationError(`Could not save priority: ${(error as Error).message}`);
    } finally {
      setSaving(false);
    }
  }
  async function setStatus(item: Item, status: string) {
    if (saving || !canEdit || status === item.status) return;
    setSaving(true);
    setMutationError("");
    try {
      await saveOpportunityStatus(workspace, item.id, status, item.status);
      await onRefresh();
      setNotice("Status saved.");
    } catch (error) {
      setMutationError(`Could not save status: ${(error as Error).message}`);
    } finally {
      setSaving(false);
    }
  }
  const columns = useMemo<ColumnDef<DataTableFeatures, Item>[]>(
    () => [
      {
        id: "select",
        size: 40,
        enableColumnFilter: false,
        enableHiding: false,
        enableSorting: false,
        header: ({ table }) => (
          <Subscribe source={table.store}>
            {() => (
              <Checkbox
                disabled={
                  !table.getRowModel().rows.some((row) => row.getCanSelect())
                }
                aria-label="Select page"
                checked={
                  table.getIsAllPageRowsSelected() ||
                  (table.getIsSomePageRowsSelected() ? "indeterminate" : false)
                }
                onCheckedChange={(value) =>
                  table.toggleAllPageRowsSelected(Boolean(value))
                }
              />
            )}
          </Subscribe>
        ),
        cell: ({ row }) => (
          <Subscribe
            source={row.table.atoms.rowSelection}
            selector={(selection) => selection[row.id] === true}
          >
            {(isSelected) => (
              <Checkbox
                disabled={!row.getCanSelect()}
                aria-label={`Select ${row.original.name}`}
                checked={isSelected}
                onCheckedChange={(value) => row.toggleSelected(Boolean(value))}
              />
            )}
          </Subscribe>
        ),
      },
      {
        accessorKey: "name",
        size: 560,
        enableColumnFilter: true,
        meta: {
          label: "Title",
          placeholder: "Search titles…",
          variant: "text",
        },
        enableHiding: false,
        header: ({ column }) => (
          <DataTableColumnHeader column={column} label={labels[column.id]} />
        ),
        cell: ({ row }) => (
          <button
            title={row.original.name}
            className="block w-full min-w-0 truncate text-left font-medium hover:underline"
            onClick={() => onOpen(row.original.id)}
          >
            {row.original.name}
          </button>
        ),
      },
      {
        id: "status",
        accessorFn: (item) => (item.archived ? "archived" : item.status),
        size: 170,
        enableColumnFilter: true,
        meta: {
          label: "Status",
          variant: "select",
          multiple: true,
          options: [...Object.keys(lifecycleLabels), "archived"].map(
            (value) => ({
              value,
              label: labels[value],
              icon: icons[value],
              count: items.filter(
                (item) => (item.archived ? "archived" : item.status) === value,
              ).length,
            }),
          ),
        },
        header: ({ column }) => (
          <DataTableColumnHeader column={column} label={labels[column.id]} />
        ),
        cell: ({ row }) =>
          canEdit && !row.original.archived ? (
            <ValuePicker
              label={`Set status for ${row.original.name}`}
              value={row.original.status}
              options={Object.keys(lifecycleLabels)}
              disabled={saving}
              onSelect={(value) => void setStatus(row.original, value)}
            />
          ) : (
            <Pill
              value={row.original.archived ? "archived" : row.original.status}
            />
          ),
      },
      {
        id: "priority",
        size: 170,
        enableColumnFilter: true,
        meta: {
          label: "Priority",
          variant: "select",
          multiple: true,
          options: ["high", "medium", "low", "unprioritized"].map((value) => ({
            value,
            label: labels[value],
            icon: icons[value],
            count: items.filter(
              (item) => (item.priority || "unprioritized") === value,
            ).length,
          })),
        },
        accessorFn: (r) => r.priority || "unprioritized",
        header: ({ column }) => (
          <DataTableColumnHeader column={column} label={labels[column.id]} />
        ),
        sortFn: (a, b) =>
          ((({ high: 0, medium: 1, low: 2 }) as Record<string, number>)[
            a.original.priority ?? ""
          ] ?? 3) -
          (({ high: 0, medium: 1, low: 2 } as Record<string, number>)[
            b.original.priority ?? ""
          ] ?? 3),
        cell: ({ row, getValue }) =>
          canEdit ? (
            <ValuePicker
              label={`Set priority for ${row.original.name}`}
              value={getValue<string>()}
              options={priorities}
              disabled={saving}
              onSelect={(value) => void setPriority(row.original.id, value)}
            />
          ) : (
            <Pill value={getValue<string>()} />
          ),
      },
      {
        accessorKey: "feedback_count",
        size: 170,
        enableColumnFilter: false,
        meta: { label: labels["feedback_count"] },
        header: ({ column }) => (
          <DataTableColumnHeader column={column} label={labels[column.id]} />
        ),
        cell: ({ getValue }) =>
          `${getValue<number>()} ${getValue<number>() === 1 ? "request" : "requests"}`,
      },
      {
        accessorKey: "created_at",
        size: 170,
        enableColumnFilter: false,
        meta: { label: labels["created_at"] },
        header: ({ column }) => (
          <DataTableColumnHeader column={column} label={labels[column.id]} />
        ),
        cell: ({ getValue }) => (
          <time
            dateTime={getValue<string>()}
            title={new Date(getValue<string>()).toLocaleString()}
            className="text-muted-foreground"
          >
            {new Date(getValue<string>()).toLocaleDateString(undefined, {
              month: "short",
              day: "numeric",
            })}
          </time>
        ),
      },
    ],
    [items, onOpen, canEdit, saving, workspace, onRefresh],
  );
  const table = useTable(
    {
      features: dataTableFeatures,
      data: activeItems,
      columns,
      enableRowSelection: canEdit && !saving,
      getRowId: (r) => r.id,
      state: { sorting, columnFilters: filters, rowSelection },
      onRowSelectionChange: setRowSelection,
      onSortingChange: setSorting,
      onColumnFiltersChange: (update) => {
        const next = typeof update === "function" ? update(filters) : update;
        const status = next.find((filter) => filter.id === "status");
        const values = status?.value as string[] | undefined;
        if (values?.includes("archived") && values.length > 1) {
          // Archived is its own view so Archive and Restore always target one scope.
          const value = showArchived
            ? values.filter((item) => item !== "archived")
            : ["archived"];
          setFilters(
            next.map((filter) =>
              filter.id === "status" ? { ...filter, value } : filter,
            ),
          );
        } else {
          setFilters(next);
        }
        if (showArchived || values?.includes("archived")) {
          setRowSelection({});
          setNotice("");
        }
      },
      initialState: { pagination: { pageIndex: 0, pageSize: 10 } },
    },
    (state) => state,
  );
  const selectedIds = table
    .getFilteredSelectedRowModel()
    .rows.map((row) => row.id);
  async function applyBulk(
    patch: { status?: string; archived?: boolean },
    label: string,
  ) {
    if (!selectedIds.length || saving || !canEdit) return;
    setSaving(true);
    setMutationError("");
    try {
      await api(
        "/opportunities/bulk",
        {
          method: "PATCH",
          body: JSON.stringify({
            ids: selectedIds,
            ...patch,
            expected_statuses: Object.fromEntries(
              items
                .filter((item) => selectedIds.includes(item.id))
                .map((item) => [item.id, item.status]),
            ),
          }),
        },
        workspace,
      );
      setNotice(`${label} for ${selectedIds.length} opportunities.`);
      table.resetRowSelection();
      await onRefresh();
    } catch (error) {
      setMutationError((error as Error).message);
    } finally {
      setSaving(false);
    }
  }
  const bulkActions = canEdit && selectedIds.length > 0 && (
    <fieldset disabled={saving} className="opportunity-bulk-actions">
      <span>{selectedIds.length} selected</span>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="outline">
            Set status
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent>
          {[
            "considering",
            "planned",
            "in_progress",
            "shipped",
            "not_pursuing",
          ].map((status) => (
            <DropdownMenuItem
              key={status}
              onSelect={() => applyBulk({ status }, "Status updated")}
            >
              <Pill value={status} />
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      <Button
        size="sm"
        variant="outline"
        onClick={() =>
          applyBulk(
            { archived: !showArchived },
            showArchived ? "Restored" : "Archived",
          )
        }
      >
        {showArchived ? "Restore" : "Archive"}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => table.resetRowSelection()}
      >
        Clear selection
      </Button>
    </fieldset>
  );
  const toolbar = (
    <DataTableToolbar table={table}>
      <DataTableSortMenu table={table} />
    </DataTableToolbar>
  );
  const visible = table
    .getPrePaginatedRowModel()
    .rows.map((row) => row.original);
  return (
    <div className="opportunity-views">
      <div className="opportunity-view-header">
        <ViewSwitch
          value={view}
          views={["board", "list", "table"]}
          onChange={setView}
          label="Opportunity view"
        />
        <span className="opportunity-result-count">
          {visible.length}{" "}
          {visible.length === 1 ? "opportunity" : "opportunities"}
        </span>
      </div>
      {canEdit && (
        <BatchPriority
          workspace={workspace}
          selectedIds={selectedIds}
          filteredIds={visible.map((item) => item.id)}
          disabled={saving || !canEdit}
          onRefresh={onRefresh}
        />
      )}
      {mutationError && (
        <p role="alert" className="text-sm text-destructive">
          {mutationError}
        </p>
      )}
      {saving && (
        <p role="status" className="text-sm text-muted-foreground">
          Saving changes…
        </p>
      )}
      {notice && (
        <p role="status" className="text-sm text-muted-foreground">
          {notice}
        </p>
      )}
      {view === "table" ? (
        <DataTable table={table} className="polished-table">
          {toolbar}
          {bulkActions}
        </DataTable>
      ) : (
        <>
          {toolbar}
          {visible.length === 0 ? (
            <div className="opportunity-empty-results">
              <p>No opportunities match your filters.</p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => table.resetColumnFilters()}
              >
                Clear filters
              </Button>
            </div>
          ) : (
            <OpportunityKanban
              items={visible}
              allItems={activeItems}
              view={view}
              onOpen={onOpen}
              disabled={!canEdit || saving || showArchived}
              onCommit={async (next) => {
                if (saving || !canEdit) return false;
                setSaving(true);
                setMutationError("");
                try {
                  await api(
                    "/opportunities/board",
                    {
                      method: "POST",
                      body: JSON.stringify({
                        items: next.map((item, index) => ({
                          id: item.id,
                          status: item.status,
                          expected_status: items.find(
                            (original) => original.id === item.id,
                          )!.status,
                          order: index,
                        })),
                      }),
                    },
                    workspace,
                  );
                  setSorting([]);
                  setNotice("Board order and status saved.");
                  await onRefresh();
                  return true;
                } catch (error) {
                  setMutationError((error as Error).message);
                  return false;
                } finally {
                  setSaving(false);
                }
              }}
            />
          )}
        </>
      )}
    </div>
  );
}
