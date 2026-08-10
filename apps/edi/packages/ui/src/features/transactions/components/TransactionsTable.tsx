import { DataTable } from '@soopa/ui/components/ui/data-table';
import {
  createColumnHelper,
  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { Database } from 'lucide-react';
import React from 'react';
import { Badge } from '../../../components/ui/badge';
import { TRANSACTION_STATUS_GROUPS } from '../constants';

// ─── Types ───────────────────────────────────────────────────────────────────

interface ColumnDef<T> {
  key: string;
  label: string;
  render?: (item: T) => React.ReactNode;
  className?: string;
}

interface TransactionsTableProps<T> {
  columns: ColumnDef<T>[];
  data: T[];
  isLoading: boolean;
  renderExpanded: (item: T) => React.ReactNode;
  headerToolbar?: React.ReactNode;
  onLoadMore?: () => void;
  hasMore?: boolean;
  renderAction?: (item: T) => React.ReactNode;
  enableRowSelection?: boolean;
  onSelectionChange?: (selectedRows: T[]) => void;
  rowSelection?: Record<string, boolean>;
  onRowSelectionChange?: (rowSelection: Record<string, boolean>) => void;
}

// ─── Status Badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status?: string }) {
  if (!status) return null;
  const upper = status.toUpperCase();

  if (TRANSACTION_STATUS_GROUPS.SUCCESS.has(upper)) {
    return (
      <Badge className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100 border-0">
        {upper}
      </Badge>
    );
  }
  if (TRANSACTION_STATUS_GROUPS.ERROR.has(upper)) {
    return <Badge className="bg-red-100 text-red-700 hover:bg-red-100 border-0">{upper}</Badge>;
  }
  if (TRANSACTION_STATUS_GROUPS.PENDING.has(upper)) {
    return (
      <Badge className="bg-amber-100 text-amber-700 hover:bg-amber-100 border-0">{upper}</Badge>
    );
  }
  return <Badge className="bg-slate-100 text-slate-700 hover:bg-slate-100 border-0">{upper}</Badge>;
}

// ─── Direction Badge ──────────────────────────────────────────────────────────

function DirectionBadge({ direction }: { direction?: string }) {
  if (!direction) return <span className="text-slate-400">—</span>;
  const upper = direction.toUpperCase();
  if (upper === 'INBOUND') {
    return (
      <Badge className="bg-blue-100 text-blue-700 hover:bg-blue-100 border-0 font-mono text-xs">
        ↓ INBOUND
      </Badge>
    );
  }
  if (upper === 'OUTBOUND') {
    return (
      <Badge className="bg-violet-100 text-violet-700 hover:bg-violet-100 border-0 font-mono text-xs">
        ↑ OUTBOUND
      </Badge>
    );
  }
  return <Badge className="bg-slate-100 text-slate-600 border-0">{direction}</Badge>;
}

// ─── Table ────────────────────────────────────────────────────────────────────

export function TransactionsTable<T extends { id: string; trace_id?: string; status?: string }>({
  columns,
  data,
  isLoading,
  renderExpanded,
  headerToolbar,
  onLoadMore,
  hasMore,
  renderAction,
  enableRowSelection,
  onSelectionChange,
  rowSelection: controlledRowSelection,
  onRowSelectionChange,
}: TransactionsTableProps<T>) {
  const [internalRowSelection, setInternalRowSelection] = React.useState({});
  const rowSelection =
    controlledRowSelection !== undefined ? controlledRowSelection : internalRowSelection;
  const setRowSelection =
    controlledRowSelection !== undefined
      ? (updater: any) => {
          const newValue =
            typeof updater === 'function' ? updater(controlledRowSelection) : updater;
          if (onRowSelectionChange) {
            onRowSelectionChange(newValue);
          }
        }
      : setInternalRowSelection;

  const tanstackColumns = React.useMemo(() => {
    const columnHelper = createColumnHelper<T>();
    const cols = [];

    if (enableRowSelection) {
      cols.push(
        columnHelper.display({
          id: 'select',
          header: ({ table }) => (
            <input
              type="checkbox"
              className="w-4 h-4 rounded border-slate-300 text-primary focus:ring-primary cursor-pointer"
              aria-label="Select all transactions"
              checked={table.getIsAllRowsSelected()}
              ref={(input) => {
                if (input) input.indeterminate = table.getIsSomeRowsSelected();
              }}
              onChange={table.getToggleAllRowsSelectedHandler()}
            />
          ),
          cell: ({ row }) => (
            <input
              type="checkbox"
              className="w-4 h-4 rounded border-slate-300 text-primary focus:ring-primary cursor-pointer"
              aria-label={`Select transaction ${row.original.trace_id ?? row.original.id}`}
              checked={row.getIsSelected()}
              disabled={!row.getCanSelect()}
              onChange={row.getToggleSelectedHandler()}
              onClick={(e) => e.stopPropagation()}
            />
          ),
          meta: { className: 'w-[40px]' },
        }),
      );
    }

    cols.push(
      ...columns.map((col) => {
        // @ts-expect-error key is used as accessor
        return columnHelper.accessor(col.key, {
          header: col.label,
          meta: { className: col.className },
          cell: (info) => {
            const item = info.row.original;
            const value = info.getValue();

            if (col.render) {
              return col.render(item);
            }
            if (col.key === 'status') {
              return <StatusBadge status={item.status} />;
            }
            if (col.key === 'direction') {
              return <DirectionBadge direction={value as string} />;
            }
            return (
              <span className="text-foreground font-medium text-sm">
                {(value as string | React.ReactNode) || (
                  <span className="text-muted-foreground font-normal italic">—</span>
                )}
              </span>
            );
          },
        });
      }),
    );

    if (renderAction) {
      cols.push(
        columnHelper.display({
          id: 'actions',
          header: '',
          cell: (info) => (
            <div className="flex justify-end" onClick={(e) => e.stopPropagation()}>
              {renderAction(info.row.original)}
            </div>
          ),
        }),
      );
    }

    return cols;
  }, [columns, renderAction, enableRowSelection]);

  const table = useReactTable({
    data,
    columns: tanstackColumns,
    getCoreRowModel: getCoreRowModel(),
    getRowCanExpand: () => true,
    getExpandedRowModel: getExpandedRowModel(),
    state: {
      rowSelection,
    },
    enableRowSelection: enableRowSelection,
    onRowSelectionChange: setRowSelection,
    getRowId: (row) => row.id,
  });

  React.useEffect(() => {
    if (onSelectionChange) {
      const selectedRows = table.getSelectedRowModel().rows.map((row) => row.original);
      onSelectionChange(selectedRows);
    }
  }, [rowSelection, onSelectionChange, table]);

  return (
    <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm">
      {headerToolbar && (
        <div className="border-b border-slate-200 bg-slate-50/50 p-4">{headerToolbar}</div>
      )}
      <DataTable
        table={table}
        isLoading={isLoading}
        dataLength={data.length}
        emptyIcon={<Database className="w-8 h-8" />}
        emptyTitle="No transactions found"
        columnsLength={tanstackColumns.length}
        hasMore={hasMore}
        onLoadMore={onLoadMore}
        renderExpandedRow={(row) => <div className="p-6">{renderExpanded(row.original)}</div>}
      />
    </div>
  );
}
