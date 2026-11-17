import { selectionColumn } from "@/components/table-selection-column";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { useMemo, useState, type ReactNode } from "react";
import { useTable, type ColumnDef } from "@tanstack/react-table";
import { DataTable } from "@/registry/bases/radix/components/data-table/data-table";
import { DataTableToolbar } from "@/registry/bases/radix/components/data-table/data-table-toolbar";
import { DataTableColumnHeader } from "@/registry/bases/radix/components/data-table/data-table-column-header";
import { DataTableSortMenu } from "@/registry/bases/radix/components/data-table/data-table-sort-menu";
import {
  dataTableFeatures,
  type DataTableFeatures,
} from "@/lib/data-table-features";
import { TaskStatusSelect, taskStatusIcons } from "./task-list";
import { taskStatuses, type Task, type TaskStatus } from "./task-api";

export function TaskTable({
  tasks,
  href,
  canEdit,
  saving,
  onStatus,
  children,
  onBulkStatus,
}: {
  onBulkStatus: (tasks: Task[], status: TaskStatus) => Promise<string[]>;
  children?: (tasks: Task[]) => ReactNode;
  tasks: Task[];
  href: (task: Task) => string;
  canEdit: boolean;
  saving: boolean;
  onStatus: (task: Task, status: TaskStatus) => void;
}) {
  const [bulkSaving, setBulkSaving] = useState(false);
  const columns = useMemo<ColumnDef<DataTableFeatures, Task>[]>(
    () => [
      ...(canEdit ? [selectionColumn<Task>((task) => task.title)] : []),
      {
        accessorKey: "title",
        size: 370,
        enableColumnFilter: true,
        meta: { label: "Title" },
        header: ({ column }) => (
          <DataTableColumnHeader column={column} label="Title" />
        ),
        cell: ({ row }) => (
          <a
            href={href(row.original)}
            className="block truncate font-medium hover:underline"
            title={row.original.title}
          >
            {row.original.title}
          </a>
        ),
      },
      {
        accessorKey: "opportunity_name",
        size: 260,
        enableColumnFilter: true,
        meta: {
          label: "Opportunity",
          variant: "select",
          options: [...new Set(tasks.map((task) => task.opportunity_name))].map(
            (value) => ({ value, label: value }),
          ),
        },
        header: ({ column }) => (
          <DataTableColumnHeader column={column} label="Opportunity" />
        ),
        cell: ({ row }) => (
          <a
            href={`#opportunities?id=${encodeURIComponent(row.original.opportunity_id)}`}
            title={row.original.opportunity_name}
            className="block truncate hover:underline"
          >
            {row.original.opportunity_name}
          </a>
        ),
      },
      {
        id: "status",
        accessorFn: (task) => task.status,
        size: 145,
        enableColumnFilter: true,
        meta: {
          label: "Status",
          variant: "select",
          options: Object.entries(taskStatuses).map(([value, label]) => ({
            value,
            label,
            icon: taskStatusIcons[value as TaskStatus],
            count: tasks.filter((task) => task.status === value).length,
          })),
        },
        header: ({ column }) => (
          <DataTableColumnHeader column={column} label="Status" />
        ),
        cell: ({ row }) =>
          canEdit ? (
            <TaskStatusSelect
              label={`Status for ${row.original.title}`}
              status={row.original.status}
              disabled={saving}
              onChange={(status) => onStatus(row.original, status)}
            />
          ) : (
            taskStatuses[row.original.status]
          ),
      },
      {
        id: "assignee",
        accessorFn: (task) => task.assignee_name ?? "Unassigned",
        size: 240,
        enableColumnFilter: true,
        meta: {
          label: "Assignee",
          variant: "select",
          options: [
            ...new Set(tasks.map((task) => task.assignee_name ?? "Unassigned")),
          ].map((value) => ({ value, label: value })),
        },
        header: ({ column }) => (
          <DataTableColumnHeader column={column} label="Assignee" />
        ),
        cell: ({ getValue }) => (
          <span
            className="block truncate text-muted-foreground"
            title={getValue<string>()}
          >
            {getValue<string>()}
          </span>
        ),
      },
    ],
    [tasks, href, canEdit, saving, onStatus],
  );
  const table = useTable(
    {
      features: dataTableFeatures,
      data: tasks,
      columns,
      getRowId: (task) => task.id,
      enableRowSelection: canEdit,
      initialState: { pagination: { pageIndex: 0, pageSize: 10 } },
    },
    (state) => state,
  );
  const selected = table
    .getFilteredSelectedRowModel()
    .rows.map((row) => row.original);
  async function bulkStatus(status: TaskStatus) {
    setBulkSaving(true);
    try {
      const saved = await onBulkStatus(selected, status);
      table.setRowSelection((current) =>
        Object.fromEntries(
          Object.entries(current).filter(([id]) => !saved.includes(id)),
        ),
      );
    } finally {
      setBulkSaving(false);
    }
  }
  const bulkActions = canEdit && selected.length > 0 && (
    <div
      className="flex flex-wrap items-center gap-2"
      aria-label="Task bulk actions"
    >
      <span className="text-sm text-muted-foreground">
        {selected.length} selected
      </span>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="outline" disabled={saving || bulkSaving}>
            Change status
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent>
          {Object.entries(taskStatuses).map(([value, label]) => (
            <DropdownMenuItem
              key={value}
              onSelect={() => void bulkStatus(value as TaskStatus)}
            >
              {label}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      <Button
        size="sm"
        variant="ghost"
        disabled={bulkSaving}
        onClick={() => table.resetRowSelection()}
      >
        Clear selection
      </Button>
    </div>
  );
  const toolbar = (
    <DataTableToolbar table={table} globalFilterPlaceholder="Search tasks…">
      <DataTableSortMenu table={table} />
    </DataTableToolbar>
  );
  if (children)
    return (
      <div className="space-y-3">
        {toolbar}
        {children(table.getSortedRowModel().rows.map((row) => row.original))}
      </div>
    );
  return (
    <DataTable
      table={table}
      className="polished-table"
      aria-label="Tasks table"
    >
      {toolbar}
      {bulkActions}
    </DataTable>
  );
}
