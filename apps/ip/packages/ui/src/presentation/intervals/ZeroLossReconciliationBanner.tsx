import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  CopyableIdPill,
  DataTable,
  StatCard,
  StatusBadge,
  StatusTone,
} from '@soopa/ui';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { CheckCircle2, CopyCheck, Database, ExternalLink, Layers, ShieldAlert } from 'lucide-react';
import React, { useMemo } from 'react';
import { BatchManifestStatus, PriorityLane } from '../../domain/enums';
import type { BatchManifestSummary, BatchReconciliationOverview } from '../../domain/intervals';
import { formatRelativeTimestamp } from '../shared/status-mapping';

export interface ZeroLossReconciliationBannerProps {
  readonly overview: BatchReconciliationOverview | undefined;
  readonly isLoading?: boolean;
  readonly onInspectTrace?: (traceId: string) => void;
  readonly showRecentBatchesTable?: boolean;
}

function mapBatchStatusTone(status: string, quarantinedHeldCount: number) {
  if (status === BatchManifestStatus.FAILED) {
    return StatusTone.CRITICAL;
  }
  if (status === BatchManifestStatus.QUARANTINED || quarantinedHeldCount > 0) {
    return StatusTone.WARNING;
  }
  if (status === BatchManifestStatus.COMPLETED) {
    return StatusTone.HEALTHY;
  }
  return StatusTone.REPLAY;
}

function mapPriorityBadgeVariant(priority: string): 'destructive' | 'default' | 'secondary' {
  if (priority === PriorityLane.P0_CRITICAL) {
    return 'destructive';
  }
  if (priority === PriorityLane.P1_LIVE) {
    return 'default';
  }
  return 'secondary';
}

export function ZeroLossReconciliationBanner({
  overview,
  isLoading = false,
  onInspectTrace,
  showRecentBatchesTable = true,
}: ZeroLossReconciliationBannerProps) {
  const rawTotal = overview?.rawIngestedTotal ?? 0;
  const validTotal = overview?.validCanonicalTotal ?? 0;
  const duplicatesTotal = overview?.duplicatesDroppedTotal ?? 0;
  const quarantinedTotal = overview?.quarantinedHeldTotal ?? 0;
  const inFlightTotal = overview?.inFlightReadingsTotal ?? 0;
  const isBalanced = overview?.isZeroLossBalanced ?? true;

  const recentBatches = useMemo(
    () => [...(overview?.recentBatches ?? [])],
    [overview?.recentBatches],
  );

  const columns = useMemo<ColumnDef<BatchManifestSummary>[]>(
    () => [
      {
        accessorKey: 'batchId',
        header: 'Batch ID',
        cell: ({ row }) => <CopyableIdPill value={row.original.batchId} truncateLength={18} />,
      },
      {
        accessorKey: 'streamName',
        header: 'Stream',
        cell: ({ row }) => (
          <span className="font-mono text-xs font-medium text-foreground">
            {row.original.streamName}
          </span>
        ),
      },
      {
        accessorKey: 'priorityLane',
        header: 'QoS Lane',
        cell: ({ row }) => (
          <Badge variant={mapPriorityBadgeVariant(row.original.priorityLane)}>
            {row.original.priorityLane}
          </Badge>
        ),
      },
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => (
          <StatusBadge
            label={row.original.status}
            tone={mapBatchStatusTone(row.original.status, row.original.quarantinedHeldCount)}
          />
        ),
      },
      {
        id: 'accounting',
        header: 'Raw / Valid / Dup / Quar',
        cell: ({ row }) => {
          const b = row.original;
          return (
            <span className="font-mono text-xs tabular-nums">
              {b.rawIngestedCount.toLocaleString()} / {b.validCanonicalCount.toLocaleString()} /{' '}
              {b.duplicatesDroppedCount.toLocaleString()} /{' '}
              <span
                className={
                  b.quarantinedHeldCount > 0 ? 'font-semibold text-destructive' : undefined
                }
              >
                {b.quarantinedHeldCount.toLocaleString()}
              </span>
            </span>
          );
        },
      },
      {
        accessorKey: 'deliveryReceiptId',
        header: 'Settlement Receipt',
        cell: ({ row }) =>
          row.original.deliveryReceiptId ? (
            <CopyableIdPill value={row.original.deliveryReceiptId} truncateLength={16} />
          ) : (
            <span className="text-xs text-muted-foreground">Pending</span>
          ),
      },
      {
        accessorKey: 'createdAt',
        header: 'Buffered',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground tabular-nums">
            {formatRelativeTimestamp(row.original.createdAt)}
          </span>
        ),
      },
      {
        id: 'actions',
        header: 'Actions',
        cell: ({ row }) =>
          onInspectTrace ? (
            <Button
              type="button"
              variant="outline"
              size="xs"
              onClick={(e) => {
                e.stopPropagation();
                onInspectTrace(row.original.traceId);
              }}
            >
              <ExternalLink className="h-3 w-3" />
              <span>Trace</span>
            </Button>
          ) : null,
      },
    ],
    [onInspectTrace],
  );

  const table = useReactTable({
    data: recentBatches,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="space-y-4">
      <section
        aria-label="Interval reconciliation stat cards"
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4"
      >
        <StatCard
          title="Raw Ingested Readings"
          value={rawTotal.toLocaleString()}
          subtitle={`${overview?.totalBatches ?? 0} macro-batches`}
          icon={<Database />}
        />
        <StatCard
          title="Valid Canonical"
          value={validTotal.toLocaleString()}
          subtitle={`${overview?.completedBatches ?? 0} completed batches`}
          icon={<CheckCircle2 />}
        />
        <StatCard
          title="Duplicates Dropped"
          value={duplicatesTotal.toLocaleString()}
          subtitle="Idempotent window dedup"
          icon={<CopyCheck />}
        />
        <StatCard
          title="Quarantined / In-Flight"
          value={`${quarantinedTotal.toLocaleString()} / ${inFlightTotal.toLocaleString()}`}
          subtitle={`${overview?.failedBatches ?? 0} failed batches`}
          icon={<ShieldAlert />}
        />
      </section>

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0 pb-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <span>Zero-Missing-Data Accounting Equation</span>
              <Badge variant={isBalanced ? 'success' : 'destructive'}>
                {isBalanced ? 'ZERO-LOSS BALANCED' : 'RECONCILIATION IMBALANCE'}
              </Badge>
            </CardTitle>
            <CardDescription className="mt-1">
              Mathematical invariant across L1 Raw Buffer, L2 Deduplication, L3 VEE Validation, and
              In-Flight batches.
            </CardDescription>
          </div>
          <div className="rounded-md border border-border bg-muted/50 px-3 py-1.5 font-mono text-xs text-foreground tabular-nums">
            Raw ({rawTotal.toLocaleString()}) = Valid ({validTotal.toLocaleString()}) + Dup (
            {duplicatesTotal.toLocaleString()}) + Quar ({quarantinedTotal.toLocaleString()}) +
            In-Flight ({inFlightTotal.toLocaleString()})
          </div>
        </CardHeader>

        {showRecentBatchesTable ? (
          <CardContent>
            <DataTable
              table={table}
              columnsLength={columns.length}
              isLoading={isLoading}
              dataLength={recentBatches.length}
              ariaLabel="Recent interval macro-batches"
              emptyIcon={<Layers className="h-5 w-5" />}
              emptyTitle="No Interval Macro-Batches Buffered"
              emptyDescription="Ingest a high-frequency interval batch via L0/L1 ingress to populate the reconciliation ledger."
              onRowClick={
                onInspectTrace ? (row) => onInspectTrace(row.original.traceId) : undefined
              }
            />
          </CardContent>
        ) : null}
      </Card>
    </div>
  );
}
