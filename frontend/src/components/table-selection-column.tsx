import { Subscribe, type RowData, type ColumnDef } from "@tanstack/react-table";
import { Checkbox } from "@/components/ui/checkbox";
import type { DataTableFeatures } from "@/lib/data-table-features";
export function selectionColumn<T extends RowData>(
  label: (item: T) => string,
): ColumnDef<DataTableFeatures, T> {
  return {
    id: "select",
    size: 40,
    enableSorting: false,
    enableHiding: false,
    enableColumnFilter: false,
    header: ({ table }) => (
      <Subscribe source={table.store}>
        {() => (
          <Checkbox
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
        {(selected) => (
          <Checkbox
            aria-label={`Select ${label(row.original)}`}
            checked={selected}
            onCheckedChange={(value) => row.toggleSelected(Boolean(value))}
          />
        )}
      </Subscribe>
    ),
  };
}
