import {
  type ApiProblem,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  CopyableIdPill,
  DataTable,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormRow,
  Input,
} from '@soopa/ui';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { BarChart3, Check, Receipt, Search } from 'lucide-react';
import React, { useMemo, useState } from 'react';
import type { DailyTouRollup } from '../../domain/intervals';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';

export interface DailyTouBillingRollupsTableProps {
  readonly rollups: readonly DailyTouRollup[];
  readonly isLoading?: boolean;
  readonly selectedFeederId: string | null;
  readonly searchDeviceId: string;
  readonly onSearchDeviceIdChange: (value: string) => void;
  readonly onInspectDeviceCurve: (sourceDeviceId: string) => void;
  readonly onRecordSettlementReceipt?: (batchId: string, receiptId: string) => Promise<boolean>;
  readonly isRecordingReceipt?: boolean;
  readonly receiptProblem?: ApiProblem | null;
}

export function DailyTouBillingRollupsTable({
  rollups,
  isLoading = false,
  selectedFeederId,
  searchDeviceId,
  onSearchDeviceIdChange,
  onInspectDeviceCurve,
  onRecordSettlementReceipt,
  isRecordingReceipt = false,
  receiptProblem = null,
}: DailyTouBillingRollupsTableProps) {
  const [receiptModalBatchId, setReceiptModalBatchId] = useState<string | null>(null);
  const [receiptInput, setReceiptInput] = useState('');

  const filteredData = useMemo(() => {
    const query = searchDeviceId.trim().toLowerCase();
    return rollups.filter((r) => {
      if (selectedFeederId && r.feederId !== selectedFeederId) {
        return false;
      }
      if (query) {
        return (
          r.sourceDeviceId.toLowerCase().includes(query) ||
          r.gemDeviceId.toLowerCase().includes(query)
        );
      }
      return true;
    });
  }, [rollups, selectedFeederId, searchDeviceId]);

  const columns = useMemo<ColumnDef<DailyTouRollup>[]>(
    () => [
      {
        accessorKey: 'sourceDeviceId',
        header: 'Device ID',
        cell: ({ row }) => (
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-xs font-semibold text-foreground">
              {row.original.sourceDeviceId}
            </span>
            <span className="font-mono text-[11px] text-muted-foreground">
              GEM: {row.original.gemDeviceId}
            </span>
          </div>
        ),
      },
      {
        accessorKey: 'feederId',
        header: 'Feeder',
        cell: ({ row }) => (
          <Badge variant="outline" className="font-mono">
            {row.original.feederId}
          </Badge>
        ),
      },
      {
        accessorKey: 'peakVolume',
        header: 'Peak Volume',
        cell: ({ row }) => (
          <span className="font-mono text-xs font-medium tabular-nums">
            {row.original.peakVolume}
          </span>
        ),
      },
      {
        accessorKey: 'shoulderVolume',
        header: 'Shoulder Volume',
        cell: ({ row }) => (
          <span className="font-mono text-xs tabular-nums">{row.original.shoulderVolume}</span>
        ),
      },
      {
        accessorKey: 'offPeakVolume',
        header: 'Off-Peak Volume',
        cell: ({ row }) => (
          <span className="font-mono text-xs tabular-nums">{row.original.offPeakVolume}</span>
        ),
      },
      {
        accessorKey: 'netExportVolume',
        header: 'Net Export',
        cell: ({ row }) => (
          <span className="font-mono text-xs tabular-nums">{row.original.netExportVolume}</span>
        ),
      },
      {
        accessorKey: 'maxDemandKw',
        header: 'Max Demand (kW)',
        cell: ({ row }) => (
          <span className="font-mono text-xs font-semibold tabular-nums">
            {row.original.maxDemandKw}
          </span>
        ),
      },
      {
        id: 'intervalHealth',
        header: 'Interval Health',
        cell: ({ row }) => {
          const valid = row.original.validIntervals;
          const quar = row.original.quarantinedIntervals;
          return (
            <div className="flex items-center gap-1.5 tabular-nums">
              <Badge variant={valid >= 96 && quar === 0 ? 'success' : 'secondary'}>
                {valid} / 96 valid
              </Badge>
              {quar > 0 ? <Badge variant="destructive">{quar} quarantined</Badge> : null}
            </div>
          );
        },
      },
      {
        accessorKey: 'deliveryReceiptId',
        header: 'Settlement Receipt',
        cell: ({ row }) => {
          const receipt = row.original.deliveryReceiptId;
          if (receipt) {
            return <CopyableIdPill value={receipt} truncateLength={16} />;
          }
          if (!onRecordSettlementReceipt) {
            return <span className="text-xs text-muted-foreground">Unsettled</span>;
          }
          return (
            <Button
              type="button"
              variant="outline"
              size="xs"
              onClick={(e) => {
                e.stopPropagation();
                setReceiptModalBatchId(row.original.latestBatchId);
                setReceiptInput(`rcpt_${row.original.serviceDate.replaceAll('-', '')}_01`);
              }}
            >
              <Receipt className="h-3 w-3" />
              <span>Record Receipt</span>
            </Button>
          );
        },
      },
      {
        id: 'actions',
        header: 'Actions',
        cell: ({ row }) => (
          <Button
            type="button"
            variant="outline"
            size="xs"
            onClick={(e) => {
              e.stopPropagation();
              onInspectDeviceCurve(row.original.sourceDeviceId);
            }}
          >
            <BarChart3 className="h-3 w-3" />
            <span>Inspect 96-Slot Curve</span>
          </Button>
        ),
      },
    ],
    [onInspectDeviceCurve, onRecordSettlementReceipt],
  );

  const table = useReactTable({
    data: filteredData,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  const handleConfirmReceipt = async (): Promise<void> => {
    if (!receiptModalBatchId || !receiptInput.trim() || !onRecordSettlementReceipt) {
      return;
    }
    const result = await onRecordSettlementReceipt(receiptModalBatchId, receiptInput.trim());
    if (result === true) {
      setReceiptModalBatchId(null);
    }
  };

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2">
              <span>Daily Time-of-Use (TOU) Settlement Rollups</span>
              {selectedFeederId ? (
                <Badge variant="secondary">Feeder: {selectedFeederId}</Badge>
              ) : null}
            </CardTitle>
            <CardDescription>
              Pre-aggregated Peak, Shoulder, Off-Peak, Net Export, and Max Demand rollups per
              device. Click any row to open the 96-slot load curve &amp; batch lineage drawer.
            </CardDescription>
          </div>
          <div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute top-2.5 left-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              value={searchDeviceId}
              onChange={(e) => onSearchDeviceIdChange(e.target.value)}
              aria-label="Filter rollups by device ID"
              placeholder="Search device ID or GEM ID..."
              className="pl-8"
            />
          </div>
        </CardHeader>

        <CardContent>
          <DataTable
            table={table}
            columnsLength={columns.length}
            isLoading={isLoading}
            dataLength={filteredData.length}
            ariaLabel="Daily Time-of-Use settlement rollups"
            emptyIcon={<BarChart3 className="h-5 w-5" />}
            emptyTitle="No TOU Settlement Rollups Found"
            emptyDescription="Process an interval batch for the selected service date to compute TOU settlement rollups."
            onRowClick={(row) => onInspectDeviceCurve(row.original.sourceDeviceId)}
          />
        </CardContent>
      </Card>

      <Dialog
        open={Boolean(receiptModalBatchId)}
        onOpenChange={(open) => {
          if (!open) {
            setReceiptModalBatchId(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Record Downstream Settlement Receipt</DialogTitle>
            <DialogDescription>
              Attach the downstream billing or settlement acknowledgement receipt ID to macro-batch{' '}
              <code className="font-mono text-xs text-foreground">{receiptModalBatchId}</code>.
            </DialogDescription>
          </DialogHeader>
          <ApiProblemBanner problem={receiptProblem} />
          <FormRow label="Settlement Receipt ID" required htmlFor="settlement-receipt-input">
            <Input
              id="settlement-receipt-input"
              value={receiptInput}
              onChange={(e) => setReceiptInput(e.target.value)}
              placeholder="e.g. SETTLE-RCPT-20261029-01"
              className="font-mono"
            />
          </FormRow>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setReceiptModalBatchId(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={!receiptInput.trim() || isRecordingReceipt}
              onClick={handleConfirmReceipt}
            >
              <Check className="h-3.5 w-3.5" />
              <span>Save Receipt</span>
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
