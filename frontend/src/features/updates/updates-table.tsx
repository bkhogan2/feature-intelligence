import { normalizeColumnFilter } from "@/lib/data-table-utils";
import { selectionColumn } from "@/components/table-selection-column";
import { DataTableSortMenu } from "@/registry/bases/radix/components/data-table/data-table-sort-menu";
import { useEffect, useMemo, useState } from "react";
import { useTable, type ColumnDef } from "@tanstack/react-table";
import {
  dataTableFeatures,
  type DataTableFeatures,
} from "@/lib/data-table-features";
import { DataTable } from "@/registry/bases/radix/components/data-table/data-table";
import { DataTableToolbar } from "@/registry/bases/radix/components/data-table/data-table-toolbar";
import { DataTableColumnHeader } from "@/registry/bases/radix/components/data-table/data-table-column-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api, useAuth } from "@/lib/auth-context";

type Update = {
  id: string;
  feedback_id: string;
  request_title: string;
  body: string;
  created_at: string;
  kind: string;
  read_at: string | null;
  archived_at: string | null;
};
export function UpdatesUnreadBadge() {
  const { active, user } = useAuth();
  const workspace = active?.workspace_slug;
  const [count, setCount] = useState(0);
  useEffect(() => {
    setCount(0);
    if (!workspace) return;
    const controller = new AbortController();
    const refresh = () =>
      void api<{ count: number }>(
        "/updates/unread",
        { signal: controller.signal },
        workspace,
      )
        .then((r) => {
          if (!controller.signal.aborted) setCount(r.count);
        })
        .catch(() => {});
    refresh();
    const interval = window.setInterval(refresh, 30000);
    window.addEventListener("updates-changed", refresh);
    window.addEventListener("focus", refresh);
    return () => {
      controller.abort();
      window.clearInterval(interval);
      window.removeEventListener("updates-changed", refresh);
      window.removeEventListener("focus", refresh);
    };
  }, [workspace, user?.subject]);
  return count > 0 ? (
    <Badge
      className="ml-auto rounded-full px-1.5 py-0 text-xs"
      aria-label={`${count} unread updates`}
    >
      {count > 99 ? "99+" : count}
    </Badge>
  ) : null;
}
export function UpdatesTable({ workspace }: { workspace: string }) {
  const [items, setItems] = useState<Update[]>([]);
  const [saving, setSaving] = useState(false);
  const [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setItems([]);
    setLoading(true);
    void (async () => {
      const all: Update[] = [];
      for (let offset = 0; ; offset += 50) {
        const result = await api<{ items: Update[]; has_more: boolean }>(
          `/updates?mine=true&offset=${offset}`,
          { signal: controller.signal },
          workspace,
        );
        all.push(...result.items);
        if (!result.has_more) break;
      }
      if (!controller.signal.aborted) setItems(all);
    })()
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [workspace, reload]);
  async function open(item: Update) {
    try {
      await api(`/updates/${item.id}/read`, { method: "POST" }, workspace);
      window.dispatchEvent(new Event("updates-changed"));
      window.location.hash = `inbox?status=all&id=${item.feedback_id}&comment=${item.id}`;
    } catch (e) {
      setError((e as Error).message);
    }
  }
  const columns = useMemo<ColumnDef<DataTableFeatures, Update>[]>(
    () => [
      selectionColumn<Update>((item) => item.request_title),
      {
        id: "archive",
        accessorFn: (row) => (row.archived_at ? "Archived" : "Active"),
        enableColumnFilter: true,
        enableSorting: false,
        enableGlobalFilter: false,
        meta: {
          label: "Archive",
          variant: "select",
          options: [
            { value: "Active", label: "Active" },
            { value: "Archived", label: "Archived" },
          ],
        },
      },
      {
        accessorKey: "request_title",
        size: 360,
        header: ({ column }) => (
          <DataTableColumnHeader column={column} title="Request" />
        ),
        meta: {
          label: "Request",
        },
        enableColumnFilter: true,
        cell: ({ row }) => (
          <Button
            variant="link"
            className={`h-auto max-w-full justify-start overflow-hidden p-0 text-left ${!row.original.read_at ? "font-semibold" : "font-normal"}`}
            onClick={() => void open(row.original)}
          >
            <span className="truncate">{row.original.request_title}</span>
          </Button>
        ),
      },
      {
        id: "read",
        size: 90,
        accessorFn: (row) => (row.read_at ? "Read" : "Unread"),
        enableColumnFilter: true,
        meta: {
          label: "Status",
          variant: "select",
          options: [
            { value: "Unread", label: "Unread" },
            { value: "Read", label: "Read" },
          ],
        },
        header: ({ column }) => (
          <DataTableColumnHeader column={column} title="Status" />
        ),
        cell: ({ getValue }) => (
          <Badge variant={getValue() === "Unread" ? "default" : "secondary"}>
            {String(getValue())}
          </Badge>
        ),
      },
      {
        accessorKey: "body",
        size: 620,
        meta: { label: "Message" },
        header: "Message",
        cell: ({ getValue }) => (
          <span className="block truncate">{String(getValue())}</span>
        ),
      },
      {
        accessorKey: "created_at",
        size: 110,
        meta: { label: "Received" },
        header: ({ column }) => (
          <DataTableColumnHeader column={column} title="Received" />
        ),
        cell: ({ getValue }) =>
          new Date(String(getValue())).toLocaleDateString(undefined, {
            month: "short",
            day: "numeric",
          }),
      },
    ],
    [workspace],
  );
  const table = useTable(
    {
      features: dataTableFeatures,
      data: items,
      enableRowSelection: true,
      columns,
      getRowId: (row) => row.id,
      initialState: {
        columnVisibility: { archive: false },
        columnFilters: [
          normalizeColumnFilter({ id: "archive", value: ["Active"] }, "select"),
        ],
        pagination: { pageIndex: 0, pageSize: 10 },
        sorting: [{ id: "created_at", desc: true }],
      },
    },
    (state) => state,
  );
  const selected = table
    .getFilteredSelectedRowModel()
    .rows.map((row) => row.original.id);
  async function bulk(action: "read" | "unread" | "archive" | "restore") {
    setSaving(true);
    setError("");
    try {
      for (let offset = 0; offset < selected.length; offset += 500) {
        await api(
          "/updates/bulk",
          {
            method: "POST",
            body: JSON.stringify({
              ids: selected.slice(offset, offset + 500),
              action,
            }),
          },
          workspace,
        );
      }
      table.resetRowSelection();
      window.dispatchEvent(new Event("updates-changed"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
      setReload((value) => value + 1);
    }
  }
  return (
    <div className="space-y-4">
      {error && <p role="alert">{error}</p>}
      {loading ? (
        <p role="status">Loading updates…</p>
      ) : (
        <DataTable table={table} className="polished-table">
          <DataTableToolbar
            table={table}
            globalFilterPlaceholder="Search notifications…"
          >
            <DataTableSortMenu table={table} />
          </DataTableToolbar>
          {selected.length > 0 && (
            <div
              className="flex flex-wrap items-center gap-2"
              aria-label="Notification bulk actions"
            >
              <span className="text-sm text-muted-foreground">
                {selected.length} selected
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={saving}
                onClick={() => void bulk("read")}
              >
                Mark read
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={saving}
                onClick={() => void bulk("unread")}
              >
                Mark unread
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={saving}
                onClick={() => void bulk("archive")}
              >
                Archive
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={saving}
                onClick={() => void bulk("restore")}
              >
                Restore
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={saving}
                onClick={() => table.resetRowSelection()}
              >
                Clear selection
              </Button>
            </div>
          )}
        </DataTable>
      )}
    </div>
  );
}
