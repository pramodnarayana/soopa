import { CopyableIdPill, DataTable, StatusBadge } from '@soopa/ui';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import React, { useMemo } from 'react';
import type { SyncRun } from '../../domain/sync-run';
import { mapSyncRunStatusTone } from '../shared/status-mapping';

export interface ConnectionSyncRunsSectionProps {
  readonly runs: readonly SyncRun[];
  readonly isLoading: boolean;
  readonly onOpenTrace: (traceId: string) => void;
}

export function ConnectionSyncRunsSection({
  runs,
  isLoading,
  onOpenTrace,
}: ConnectionSyncRunsSectionProps) {
  const runRows = useMemo(() => [...runs], [runs]);

  const runColumns = useMemo<ColumnDef<SyncRun>[]>(
    () => [
      {
        accessorKey: 'runId',
        header: 'Run ID',
        cell: ({ row }) => <CopyableIdPill value={row.original.runId} truncateLength={14} />,
      },
      {
        accessorKey: 'streamName',
        header: 'Entity',
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {row.original.streamName} ({row.original.kind})
          </span>
        ),
      },
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => (
          <StatusBadge
            label={row.original.status}
            tone={mapSyncRunStatusTone(row.original.status)}
          />
        ),
      },
      {
        accessorKey: 'recordsCount',
        header: 'Records',
        cell: ({ row }) => (
          <span className="font-mono text-xs tabular-nums">{row.original.recordsCount}</span>
        ),
      },
      {
        accessorKey: 'traceId',
        header: 'Trace',
        cell: ({ row }) => <CopyableIdPill value={row.original.traceId} truncateLength={14} />,
      },
    ],
    [],
  );

  const runTable = useReactTable({
    data: runRows,
    columns: runColumns,
    getCoreRowModel: getCoreRowModel(),
  });

  if (runRows.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2 pt-2">
      <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Recent Sync Runs
      </span>
      <DataTable
        table={runTable}
        columnsLength={runColumns.length}
        isLoading={isLoading}
        dataLength={runRows.length}
        ariaLabel="Recent sync runs"
        emptyTitle="No Sync Runs Yet"
        onRowClick={(row) => onOpenTrace(row.original.traceId)}
      />
    </div>
  );
}
