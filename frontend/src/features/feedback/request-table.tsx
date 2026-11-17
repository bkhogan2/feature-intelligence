import { normalizeColumnFilter } from "@/lib/data-table-utils";
import {
  dataTableFeatures,
  type DataTableFeatures,
} from "@/lib/data-table-features";
import { DataTableToolbar } from "@/registry/bases/radix/components/data-table/data-table-toolbar";
import { DataTableSortMenu } from "@/registry/bases/radix/components/data-table/data-table-sort-menu";
import { DataTableColumnHeader } from "@/registry/bases/radix/components/data-table/data-table-column-header";
import { approveRequest, rejectRequest } from "./request-decisions";
import { useMemo, useState, useRef, useEffect } from "react";
import { BulkTriageReview } from "./bulk-triage-review";
import {
  useTable,
  Subscribe,
  type ColumnDef,
  type Column,
  type SortingState,
  type ColumnFiltersState,
  type RowSelectionState,
} from "@tanstack/react-table";
import {
  ArrowRight,
  CircleHelp,
  Archive,
  CircleDashed,
  ArrowUp,
  ArrowDown,
  ChevronsUpDown,
  PlusCircle,
  SlidersHorizontal,
  ArrowDownUp,
  MoreHorizontal,
  EyeOff,
  CheckCircle2,
  Circle,
  X,
  Check,
} from "lucide-react";
import { DataTable } from "@/registry/bases/radix/components/data-table/data-table";
import { Checkbox } from "@/components/ui/checkbox";
export type RequestPatch = {
  priority?: "high" | "medium" | "low" | null;
  archived?: boolean;
};
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
export type RequestItem = {
  id: string;
  title: string;
  description: string;
  submitted_by: string;
  submitter_name?: string;
  status: string;
  approval_status?: string | null;
  approval_error?: string | null;
  support_count: number;
  created_at: string;
  priority?: "high" | "medium" | "low" | null;
};
type Item = RequestItem;
const labels: Record<string, string> = {
  priority: "Priority",
  high: "High",
  medium: "Medium",
  low: "Low",
  unprioritized: "Unprioritized",
  title: "Title",
  status: "Status",
  support_count: "Support",
  created_at: "Received",
  new: "New",
  triaged: "Approved",
  rejected: "Rejected",
  needs_clarification: "Needs clarification",
  archived: "Archived",
};
const icons: Record<string, typeof Circle> = {
  high: ArrowUp,
  medium: ArrowRight,
  low: ArrowDown,
  unprioritized: CircleDashed,
  needs_clarification: CircleHelp,
  archived: Archive,
  new: Circle,
  triaged: CheckCircle2,
};
function Pill({ value }: { value: string }) {
  const Icon = icons[value] || Circle;
  return (
    <Badge
      variant="outline"
      className="rounded-full gap-1 font-normal whitespace-nowrap"
    >
      <Icon className="size-3.5" />
      {labels[value] || value}
    </Badge>
  );
}
export function RequestTable({
  items,
  onOpen,
  initialStatus = "all",
  initialSearch = "",
  onBulkChange,
  canEdit,
  workspace,
  onTriageConfirmed,
  onDecision,
}: {
  workspace?: string;
  onDecision?: (id: string, status: string) => void;
  onTriageConfirmed?: (ids: string[]) => void;
  items: Item[];
  onOpen: (id: string) => void;
  initialStatus?: string;
  initialSearch?: string;
  onBulkChange: (ids: string[], patch: RequestPatch) => Promise<void>;
  canEdit: boolean;
}) {
  const [reviewRequests, setReviewRequests] = useState<Item[] | null>(null);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [sorting, setSorting] = useState<SortingState>([
    { id: "created_at", desc: true },
  ]);
  const [filters, setFilters] = useState<ColumnFiltersState>(() =>
    [
      ...(initialSearch ? [{ id: "title", value: initialSearch }] : []),
      ...([
        "new",
        "triaged",
        "needs_clarification",
        "rejected",
        "archived",
      ].includes(initialStatus)
        ? [{ id: "status", value: [initialStatus] }]
        : []),
    ].map((filter) =>
      normalizeColumnFilter(filter, filter.id === "status" ? "select" : "text"),
    ),
  );
  const decisionController = useRef<AbortController | null>(null);
  useEffect(() => () => decisionController.current?.abort(), [workspace]);
  async function decide(item: Item, decision: "approve" | "reject") {
    if (!workspace || !canEdit || pending || decisionController.current) return;
    const controller = new AbortController();
    decisionController.current = controller;
    setPending(true);
    setError("");
    setNotice("");
    try {
      if (decision === "approve")
        await approveRequest(
          item.id,
          workspace,
          controller.signal,
          item.status,
        );
      else await rejectRequest(item.id, item.status, workspace);
      if (controller.signal.aborted) return;
      onDecision?.(item.id, decision === "approve" ? "triaged" : "rejected");
      setNotice(`Request ${decision === "approve" ? "approved" : "rejected"}.`);
    } catch (e) {
      if (!controller.signal.aborted) setError((e as Error).message);
    } finally {
      if (!controller.signal.aborted) {
        setPending(false);
        decisionController.current = null;
      }
    }
  }
  const columns = useMemo<ColumnDef<DataTableFeatures, Item>[]>(
    () => [
      ...(canEdit
        ? ([
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
                      aria-label="Select all requests on this page"
                      checked={
                        table.getIsAllPageRowsSelected() ||
                        (table.getIsSomePageRowsSelected()
                          ? "indeterminate"
                          : false)
                      }
                      onCheckedChange={(value) =>
                        table.toggleAllPageRowsSelected(!!value)
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
                      aria-label={`Select ${row.original.title}`}
                      checked={isSelected}
                      onCheckedChange={(value) => row.toggleSelected(!!value)}
                    />
                  )}
                </Subscribe>
              ),
            },
          ] satisfies ColumnDef<DataTableFeatures, Item>[])
        : []),
      {
        accessorKey: "title",
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
            title={row.original.title}
            className="block w-full min-w-0 truncate text-left font-medium hover:underline"
            onClick={() => onOpen(row.original.id)}
          >
            {row.original.title}
          </button>
        ),
      },
      {
        accessorKey: "status",
        size: 170,
        enableColumnFilter: true,
        meta: {
          label: "Status",
          variant: "select",
          multiple: true,
          options: [
            {
              value: "new",
              label: labels["new"],
              icon: icons["new"],
              count: items.filter((item) => item.status === "new").length,
            },
            {
              value: "rejected",
              label: labels["rejected"],
              icon: Circle,
              count: items.filter((item) => item.status === "rejected").length,
            },
            {
              value: "triaged",
              label: labels["triaged"],
              icon: icons["triaged"],
              count: items.filter((item) => item.status === "triaged").length,
            },
            {
              value: "archived",
              label: labels["archived"],
              icon: icons["archived"],
              count: items.filter((item) => item.status === "archived").length,
            },
          ],
        },
        header: ({ column }) => (
          <DataTableColumnHeader column={column} label={labels[column.id]} />
        ),
        cell: ({ row, getValue }) => (
          <div>
            <Pill value={getValue<string>()} />
            {["queued", "running"].includes(
              row.original.approval_status ?? "",
            ) && (
              <span className="ml-2 text-xs text-muted-foreground">
                Linking…
              </span>
            )}
            {row.original.approval_status === "failed" && (
              <span
                className="ml-2 text-xs text-destructive"
                title={row.original.approval_error ?? undefined}
              >
                Approval failed · retry
              </span>
            )}
          </div>
        ),
      },
      ...(canEdit && workspace
        ? [
            {
              id: "decision",
              size: 100,
              enableSorting: false,
              enableColumnFilter: false,
              enableHiding: false,
              meta: { label: "Decision" },
              header: () => "Decision",
              cell: ({ row }: { row: { original: Item } }) => (
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7 text-green-700 hover:bg-green-50 hover:text-green-800"
                    aria-label={`Approve ${row.original.title}`}
                    title="Approve"
                    disabled={
                      pending ||
                      ["queued", "running"].includes(
                        row.original.approval_status ?? "",
                      ) ||
                      row.original.status === "triaged" ||
                      row.original.status === "archived"
                    }
                    onClick={(e) => {
                      e.stopPropagation();
                      void decide(row.original, "approve");
                    }}
                  >
                    <Check className="size-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7 text-red-600 hover:bg-red-50 hover:text-red-700"
                    aria-label={`Reject ${row.original.title}`}
                    title="Reject"
                    disabled={
                      pending ||
                      ["queued", "running"].includes(
                        row.original.approval_status ?? "",
                      ) ||
                      row.original.status === "rejected" ||
                      row.original.status === "archived"
                    }
                    onClick={(e) => {
                      e.stopPropagation();
                      void decide(row.original, "reject");
                    }}
                  >
                    <X className="size-4" />
                  </Button>
                </div>
              ),
            },
          ]
        : []),
      {
        accessorKey: "support_count",
        size: 170,
        enableColumnFilter: false,
        meta: { label: labels["support_count"] },
        header: ({ column }) => (
          <DataTableColumnHeader column={column} label={labels[column.id]} />
        ),
        cell: ({ getValue }) =>
          `${getValue<number>()} ${getValue<number>() === 1 ? "supporter" : "supporters"}`,
      },
      {
        accessorKey: "created_at",
        size: 170,
        enableColumnFilter: false,
        meta: { label: labels["created_at"] },
        header: ({ column }) => (
          <DataTableColumnHeader column={column} label={labels[column.id]} />
        ),
        cell: ({ getValue }) =>
          new Date(getValue<string>()).toLocaleDateString(undefined, {
            month: "long",
            day: "numeric",
            year: "numeric",
          }),
      },
      {
        id: "actions",
        size: 48,
        enableColumnFilter: false,
        enableHiding: false,
        cell: ({ row }) => (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Actions for ${row.original.title}`}
                className="size-8"
              >
                <MoreHorizontal className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => onOpen(row.original.id)}>
                Open request
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ),
      },
    ],
    [items, onOpen, canEdit, pending, onBulkChange, workspace, onDecision],
  );
  const table = useTable(
    {
      features: dataTableFeatures,
      data: items,
      columns,
      getRowId: (r) => r.id,
      enableRowSelection: canEdit,
      onRowSelectionChange: setRowSelection,
      state: { sorting, columnFilters: filters, rowSelection },
      onSortingChange: setSorting,
      onColumnFiltersChange: (updater) => {
        setFilters(updater);
        setRowSelection({});
      },
      initialState: { pagination: { pageIndex: 0, pageSize: 10 } },
    },
    (state) => state,
  );
  const selectedIds = table
    .getFilteredSelectedRowModel()
    .rows.map((row) => row.original.id);
  const selectedActiveIds = selectedIds.filter(
    (id) => items.find((item) => item.id === id)?.status !== "archived",
  );
  const selectedArchivedIds = selectedIds.filter(
    (id) => items.find((item) => item.id === id)?.status === "archived",
  );
  const applyBulk = async (
    patch: RequestPatch,
    label: string,
    ids = selectedIds,
  ) => {
    if (!ids.length || pending || !canEdit) return;
    setPending(true);
    setError("");
    setNotice("");
    try {
      await onBulkChange(ids, patch);
      setNotice(
        `${ids.length} ${ids.length === 1 ? "request" : "requests"} ${label}.`,
      );
      setRowSelection({});
    } catch (err) {
      setError(
        `Could not save changes: ${(err as Error).message}. Refresh to check the saved state before retrying.`,
      );
    } finally {
      setPending(false);
    }
  };
  const controls = (
    <>
      <div className="flex justify-end text-xs text-muted-foreground">
        <span className="opportunity-result-count">
          {table.getFilteredRowModel().rows.length} requests
        </span>
      </div>
      {canEdit && selectedIds.length > 0 && (
        <div
          className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/40 px-3 py-2"
          aria-label="Bulk request actions"
        >
          <span className="text-sm font-medium">
            {selectedIds.length} selected
          </span>
          {workspace && selectedActiveIds.length > 0 && (
            <Button
              size="sm"
              disabled={pending || selectedIds.length > 50}
              onClick={() =>
                setReviewRequests(
                  items.filter((item) => selectedActiveIds.includes(item.id)),
                )
              }
            >
              Review triage
            </Button>
          )}
          {selectedIds.length > 50 && (
            <span className="text-xs">Review up to 50 requests at a time.</span>
          )}
          {selectedActiveIds.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              disabled={pending}
              onClick={() =>
                applyBulk({ archived: true }, "archived", selectedActiveIds)
              }
            >
              Archive selected ({selectedActiveIds.length})
            </Button>
          )}
          {selectedArchivedIds.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              disabled={pending}
              onClick={() =>
                applyBulk({ archived: false }, "restored", selectedArchivedIds)
              }
            >
              Restore selected ({selectedArchivedIds.length})
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            disabled={pending}
            onClick={() => setRowSelection({})}
          >
            Clear selection
          </Button>
        </div>
      )}
      {pending && (
        <p role="status" className="text-xs text-muted-foreground">
          Saving changes…
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="text-xs text-muted-foreground">
          {notice}
        </p>
      )}
      <DataTableToolbar table={table}>
        <DataTableSortMenu table={table} />
      </DataTableToolbar>
      {reviewRequests && workspace && canEdit && (
        <BulkTriageReview
          workspace={workspace}
          requests={reviewRequests}
          canEdit={canEdit}
          onClose={() => setReviewRequests(null)}
          onOpen={onOpen}
          onConfirmed={(ids) => {
            onTriageConfirmed?.(ids);
            setRowSelection((current) =>
              Object.fromEntries(
                Object.entries(current).filter(([id]) => !ids.includes(id)),
              ),
            );
            setNotice(`${ids.length} requests approved and moved to Approved.`);
          }}
        />
      )}
    </>
  );
  return (
    <DataTable table={table} className="polished-table">
      {controls}
    </DataTable>
  );
}
