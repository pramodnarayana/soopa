import { DataTable } from '@soopa/ui/components/ui/data-table';
import {
  createColumnHelper,
  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { Database } from 'lucide-react';
import React, { useState } from 'react';
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
}

// ─── Status Badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status?: string }) {
  if (!status) return null;
  const upper = status.toUpperCase();

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  if (TRANSACTION_STATUS_GROUPS.SUCCESS.has(upper as any)) {
    return (
      <Badge className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100 border-0">
        {upper}
      </Badge>
    );
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  if (TRANSACTION_STATUS_GROUPS.ERROR.has(upper as any)) {
    return <Badge className="bg-red-100 text-red-700 hover:bg-red-100 border-0">{upper}</Badge>;
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  if (TRANSACTION_STATUS_GROUPS.PENDING.has(upper as any)) {
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
}: TransactionsTableProps<T>) {
  const tanstackColumns = React.useMemo(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const columnHelper = createColumnHelper<any>();

    const cols = columns.map((col) => {
      return columnHelper.accessor(col.key, {
        header: col.label,
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
            <span className="text-slate-700 font-medium font-mono text-xs">
              {value || <span className="text-slate-400 font-sans font-normal">—</span>}
            </span>
          );
        },
      });
    });

    if (renderAction) {
      cols.push(
        columnHelper.display({
          id: 'actions',
          header: 'Action',
          cell: (info) => (
            <div className="flex justify-end" onClick={(e) => e.stopPropagation()}>
              {renderAction(info.row.original)}
            </div>
          ),
        }),
      );
    }

    return cols;
  }, [columns, renderAction]);

  const table = useReactTable({
    data,
    columns: tanstackColumns,
    getCoreRowModel: getCoreRowModel(),
    getRowCanExpand: () => true,
    getExpandedRowModel: getExpandedRowModel(),
  });

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
