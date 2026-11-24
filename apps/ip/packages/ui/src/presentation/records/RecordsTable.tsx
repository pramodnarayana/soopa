import {
  Button,
  CopyableIdPill,
  Input,
  StatusBadge,
  StatusTone,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@soopa/ui';
import { type ColumnDef, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import { Activity, ChevronDown, ChevronRight, Search } from 'lucide-react';
import React, { useMemo, useState } from 'react';
import type { NormalizedRecord, OutboundRecord } from '../../domain/trace';
import { formatRelativeTimestamp } from '../shared/status-mapping';
import { RecordDetail } from './RecordDetail';

export interface RecordsTableProps {
  readonly records: readonly NormalizedRecord[];
  readonly entityName: string;
  readonly isLoading?: boolean;
  readonly onSelectRecord?: (record: NormalizedRecord) => void;
  readonly onOpenTraceDetail?: (traceId: string) => void;
  readonly onOpenTraceStitches?: (traceId: string) => void;
  readonly outboundRecords?: readonly OutboundRecord[];
}

function getSingularName(name: string): string {
  if (name.endsWith('ies')) return name.slice(0, -3) + 'y';
  if (name.endsWith('s') && !name.endsWith('ss')) return name.slice(0, -1);
  return name;
}

function formatHeaderLabel(key: string): string {
  return key
    .replace(/[._]/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bId\b/g, 'ID')
    .replace(/\bRef\b/g, 'Ref')
    .trim();
}

function formatCellValue(val: unknown): string {
  if (val === null || val === undefined) return '—';
  if (typeof val === 'number') {
    return val.toLocaleString();
  }
  if (typeof val === 'object') {
    return JSON.stringify(val);
  }
  return String(val);
}

export function RecordsTable({
  records,
  entityName,
  isLoading = false,
  onSelectRecord,
  onOpenTraceDetail,
  onOpenTraceStitches,
  outboundRecords = [],
}: RecordsTableProps) {
  const [search, setSearch] = useState('');
  const [expandedRowIds, setExpandedRowIds] = useState<Set<string>>(new Set());

  const singularName = useMemo(() => getSingularName(entityName), [entityName]);

  const toggleRowExpanded = (rowId: string) => {
    setExpandedRowIds((prev) => {
      const next = new Set(prev);
      if (next.has(rowId)) {
        next.delete(rowId);
      } else {
        next.add(rowId);
      }
      return next;
    });
  };

  // Index outbound records by traceId and correlationId supporting 1-to-many fan-out
  const outboundByTrace = useMemo(() => {
    const map = new Map<string, OutboundRecord[]>();
    for (const out of outboundRecords) {
      if (out.traceId) {
        const list = map.get(out.traceId) ?? [];
        list.push(out);
        map.set(out.traceId, list);
      }
      if (out.correlationId) {
        const list = map.get(out.correlationId) ?? [];
        list.push(out);
        map.set(out.correlationId, list);
      }
    }
    return map;
  }, [outboundRecords]);

  const getOutboundsForRecord = (rec: NormalizedRecord): OutboundRecord[] => {
    return outboundByTrace.get(rec.traceId) || outboundByTrace.get(rec.sourceId) || [];
  };

  const renderDeliveryStatus = (outs: readonly OutboundRecord[]) => {
    if (!outs || outs.length === 0) {
      return <StatusBadge label="PROCESSING" tone={StatusTone.NEUTRAL} />;
    }

    if (outs.length === 1) {
      const out = outs[0]!;
      const isFailed =
        out.status === 'FAILED' ||
        (out.responseStatusCode != null && out.responseStatusCode >= 400);
      const isDelivered = out.status === 'DELIVERED' || out.responseStatusCode === 200;
      const appName = out.appId.replace(/[_-]/g, ' ').toUpperCase();
      return (
        <StatusBadge
          label={
            isFailed
              ? `${out.responseStatusCode ?? 503} FAILED (${appName})`
              : isDelivered
                ? `DELIVERED (${appName})`
                : `${out.status} (${appName})`
          }
          tone={
            isFailed ? StatusTone.CRITICAL : isDelivered ? StatusTone.HEALTHY : StatusTone.NEUTRAL
          }
        />
      );
    }

    return (
      <div className="flex flex-wrap items-center gap-1.5 max-w-[280px]">
        {outs.map((out) => {
          const isFailed =
            out.status === 'FAILED' ||
            (out.responseStatusCode != null && out.responseStatusCode >= 400);
          const isDelivered = out.status === 'DELIVERED' || out.responseStatusCode === 200;
          const appName = out.appId.replace(/[_-]/g, ' ').toUpperCase();
          return (
            <StatusBadge
              key={out.id}
              label={`${appName}: ${isFailed ? `${out.responseStatusCode ?? 'FAIL'}` : isDelivered ? '200 OK' : out.status}`}
              tone={
                isFailed
                  ? StatusTone.CRITICAL
                  : isDelivered
                    ? StatusTone.HEALTHY
                    : StatusTone.NEUTRAL
              }
            />
          );
        })}
      </div>
    );
  };

  // Client-side search across all fields of the record
  const filteredRecords = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return [...records];

    return records.filter((rec) => {
      if (rec.sourceId.toLowerCase().includes(query)) return true;
      if (rec.id.toLowerCase().includes(query)) return true;

      const dataObj = rec.canonicalData;
      if (dataObj && typeof dataObj === 'object') {
        for (const val of Object.values(dataObj)) {
          if (val !== null && val !== undefined) {
            if (String(val).toLowerCase().includes(query)) return true;
          }
        }
      }
      return false;
    });
  }, [records, search]);

  // Helper to render the common action buttons
  const renderActionsCell = (record: NormalizedRecord, rowId: string) => {
    const isExpanded = expandedRowIds.has(rowId);
    return (
      <div className="flex items-center justify-end gap-2" onClick={(e) => e.stopPropagation()}>
        <Button
          type="button"
          variant="ghost"
          size="xs"
          className="gap-1 text-xs h-7 text-muted-foreground hover:text-foreground"
          onClick={() => {
            toggleRowExpanded(rowId);
            if (onSelectRecord) onSelectRecord(record);
          }}
        >
          <span>{isExpanded ? 'Hide' : 'Details'}</span>
          {isExpanded ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" />
          )}
        </Button>
      </div>
    );
  };

  // Dynamically compute business table columns
  const columns = useMemo<ColumnDef<NormalizedRecord>[]>(() => {
    const sampleRecord = records[0]?.canonicalData;
    const isInvoice =
      entityName.toLowerCase().includes('invoice') ||
      (sampleRecord && typeof sampleRecord === 'object' && 'invoiceNumber' in sampleRecord);

    if (isInvoice) {
      return [
        {
          id: 'invoiceNumber',
          header: 'Invoice #',
          cell: ({ row }) => {
            const data = (row.original.canonicalData ?? {}) as Record<string, unknown>;
            const num = String(data.invoiceNumber ?? row.original.sourceId);
            return <CopyableIdPill value={num} truncateLength={14} />;
          },
        },
        {
          id: 'orderNumber',
          header: 'Order Ref',
          cell: ({ row }) => {
            const data = (row.original.canonicalData ?? {}) as Record<string, unknown>;
            return (
              <span className="font-mono text-xs text-muted-foreground">
                {String(data.orderNumber ?? '—')}
              </span>
            );
          },
        },
        {
          id: 'customer',
          header: 'Customer',
          cell: ({ row }) => {
            const data = (row.original.canonicalData ?? {}) as Record<string, unknown>;
            return (
              <span className="text-xs text-foreground font-medium">
                {String(data.customerRef ?? data.customer ?? '—')}
              </span>
            );
          },
        },
        {
          id: 'total',
          header: 'Total Amount',
          cell: ({ row }) => {
            const data = (row.original.canonicalData ?? {}) as Record<string, unknown>;
            const total = data.total ?? data.total_amount;
            const currency = String(data.currency ?? 'USD');
            if (total !== undefined && total !== null) {
              const formatted = Number(total).toLocaleString(undefined, {
                style: 'currency',
                currency,
              });
              return <span className="text-xs font-semibold text-foreground">{formatted}</span>;
            }
            return <span className="text-xs text-muted-foreground">—</span>;
          },
        },
        {
          id: 'deliveryStatus',
          header: 'Target Delivery',
          cell: ({ row }) => renderDeliveryStatus(getOutboundsForRecord(row.original)),
        },
        {
          id: 'receivedAt',
          header: 'Timestamp',
          cell: ({ row }) => (
            <span className="text-xs text-muted-foreground font-mono">
              {formatRelativeTimestamp(row.original.normalizedAt)}
            </span>
          ),
        },
        {
          id: 'actions',
          header: '',
          cell: ({ row }) => renderActionsCell(row.original, row.id),
        },
      ];
    }

    const isOrder =
      entityName.toLowerCase().includes('order') ||
      (sampleRecord &&
        typeof sampleRecord === 'object' &&
        ('orderNumber' in sampleRecord ||
          'order_number' in sampleRecord ||
          'line_items' in sampleRecord));

    if (isOrder) {
      return [
        {
          id: 'orderNumber',
          header: 'Order #',
          cell: ({ row }) => {
            const data = (row.original.canonicalData ?? {}) as Record<string, unknown>;
            const num = String(
              data.orderNumber ?? data.order_number ?? data.name ?? row.original.sourceId,
            );
            return <CopyableIdPill value={num} truncateLength={14} />;
          },
        },
        {
          id: 'customer',
          header: 'Customer',
          cell: ({ row }) => {
            const data = (row.original.canonicalData ?? {}) as Record<string, unknown>;
            const cust =
              data.customer && typeof data.customer === 'object'
                ? ((data.customer as Record<string, unknown>).email ??
                  (data.customer as Record<string, unknown>).name)
                : (data.customerRef ?? data.email ?? '—');
            return <span className="text-xs text-foreground font-medium">{String(cust)}</span>;
          },
        },
        {
          id: 'total',
          header: 'Order Total',
          cell: ({ row }) => {
            const data = (row.original.canonicalData ?? {}) as Record<string, unknown>;
            const total = data.total_price ?? data.total ?? data.totalAmount;
            const currency = String(data.currency ?? 'USD');
            if (total !== undefined && total !== null) {
              const formatted = Number(total).toLocaleString(undefined, {
                style: 'currency',
                currency,
              });
              return <span className="text-xs font-semibold text-foreground">{formatted}</span>;
            }
            return <span className="text-xs text-muted-foreground">—</span>;
          },
        },
        {
          id: 'deliveryStatus',
          header: 'Target Delivery',
          cell: ({ row }) => renderDeliveryStatus(getOutboundsForRecord(row.original)),
        },
        {
          id: 'receivedAt',
          header: 'Timestamp',
          cell: ({ row }) => (
            <span className="text-xs text-muted-foreground font-mono">
              {formatRelativeTimestamp(row.original.normalizedAt)}
            </span>
          ),
        },
        {
          id: 'actions',
          header: '',
          cell: ({ row }) => renderActionsCell(row.original, row.id),
        },
      ];
    }

    const isTelemetry =
      entityName.toLowerCase().includes('reading') ||
      entityName.toLowerCase().includes('interval') ||
      entityName.toLowerCase().includes('telemetry') ||
      (sampleRecord &&
        typeof sampleRecord === 'object' &&
        ('deviceId' in sampleRecord ||
          'device_id' in sampleRecord ||
          'endpoint_id' in sampleRecord));

    if (isTelemetry) {
      return [
        {
          id: 'deviceId',
          header: 'Device / Endpoint ID',
          cell: ({ row }) => {
            const data = (row.original.canonicalData ?? {}) as Record<string, unknown>;
            const id = String(
              data.deviceId ?? data.device_id ?? data.endpoint_id ?? row.original.sourceId,
            );
            return <CopyableIdPill value={id} truncateLength={14} />;
          },
        },
        {
          id: 'readingValue',
          header: 'Active Reading',
          cell: ({ row }) => {
            const data = (row.original.canonicalData ?? {}) as Record<string, unknown>;
            const val =
              data.reading_value ?? data.readingValue ?? data.reading ?? data.value ?? data.val;
            const uom = String(data.uom ?? data.unit ?? '');
            if (val !== undefined && val !== null) {
              return (
                <span className="text-xs font-semibold text-foreground font-mono">
                  {Number(val).toLocaleString()}
                  {uom ? ` ${uom}` : ''}
                </span>
              );
            }
            return <span className="text-xs text-muted-foreground">—</span>;
          },
        },
        {
          id: 'intervalTime',
          header: 'Interval Period',
          cell: ({ row }) => {
            const data = (row.original.canonicalData ?? {}) as Record<string, unknown>;
            const start = data.interval_start ?? data.timestamp ?? data.period;
            return (
              <span className="text-xs text-muted-foreground font-mono">
                {String(start ?? '—')}
              </span>
            );
          },
        },
        {
          id: 'deliveryStatus',
          header: 'Delivery Status',
          cell: ({ row }) => renderDeliveryStatus(getOutboundsForRecord(row.original)),
        },
        {
          id: 'receivedAt',
          header: 'Timestamp',
          cell: ({ row }) => (
            <span className="text-xs text-muted-foreground font-mono">
              {formatRelativeTimestamp(row.original.normalizedAt)}
            </span>
          ),
        },
        {
          id: 'actions',
          header: '',
          cell: ({ row }) => renderActionsCell(row.original, row.id),
        },
      ];
    }

    const isShipment =
      entityName.toLowerCase().includes('load') ||
      entityName.toLowerCase().includes('tender') ||
      entityName.toLowerCase().includes('shipment') ||
      (sampleRecord &&
        typeof sampleRecord === 'object' &&
        ('tender_id' in sampleRecord || 'load_id' in sampleRecord));

    if (isShipment) {
      return [
        {
          id: 'loadId',
          header: 'Load / Tender #',
          cell: ({ row }) => {
            const data = (row.original.canonicalData ?? {}) as Record<string, unknown>;
            const id = String(
              data.tender_id ?? data.load_id ?? data.shipment_number ?? row.original.sourceId,
            );
            return <CopyableIdPill value={id} truncateLength={14} />;
          },
        },
        {
          id: 'route',
          header: 'Origin → Destination',
          cell: ({ row }) => {
            const data = (row.original.canonicalData ?? {}) as Record<string, unknown>;
            const origin = String(data.origin_city ?? data.origin ?? '—');
            const dest = String(data.destination_city ?? data.destination ?? '—');
            return (
              <span className="text-xs text-foreground font-medium">
                {origin} → {dest}
              </span>
            );
          },
        },
        {
          id: 'carrier',
          header: 'Carrier',
          cell: ({ row }) => {
            const data = (row.original.canonicalData ?? {}) as Record<string, unknown>;
            return (
              <span className="text-xs text-muted-foreground">
                {String(data.carrier ?? data.scac ?? '—')}
              </span>
            );
          },
        },
        {
          id: 'deliveryStatus',
          header: 'Target Delivery',
          cell: ({ row }) => renderDeliveryStatus(getOutboundsForRecord(row.original)),
        },
        {
          id: 'receivedAt',
          header: 'Timestamp',
          cell: ({ row }) => (
            <span className="text-xs text-muted-foreground font-mono">
              {formatRelativeTimestamp(row.original.normalizedAt)}
            </span>
          ),
        },
        {
          id: 'actions',
          header: '',
          cell: ({ row }) => renderActionsCell(row.original, row.id),
        },
      ];
    }

    // Dynamic fallback for any other business entity
    const dynamicCols: ColumnDef<NormalizedRecord>[] = [
      {
        id: 'primaryIdentifier',
        header: 'Identifier',
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <span className="font-semibold text-foreground">{row.original.sourceId}</span>
            <CopyableIdPill value={row.original.sourceId} truncateLength={14} />
          </div>
        ),
      },
    ];

    // Inspect first row to discover top business attributes
    if (sampleRecord && typeof sampleRecord === 'object') {
      const excludedKeys = new Set([
        'transformation_id',
        'transformation_version',
        'extensions',
        'canonical_id',
      ]);
      const keys = Object.keys(sampleRecord)
        .filter((k) => !excludedKeys.has(k))
        .slice(0, 4);

      for (const k of keys) {
        dynamicCols.push({
          id: k,
          header: formatHeaderLabel(k),
          cell: ({ row }) => {
            const data = row.original.canonicalData as Record<string, unknown>;
            return (
              <span className="text-xs text-foreground truncate max-w-[180px] block">
                {formatCellValue(data[k])}
              </span>
            );
          },
        });
      }
    }

    dynamicCols.push({
      id: 'deliveryStatus',
      header: 'Delivery Status',
      cell: ({ row }) => renderDeliveryStatus(getOutboundsForRecord(row.original)),
    });

    dynamicCols.push({
      id: 'timestamp',
      header: 'Updated',
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground font-mono">
          {formatRelativeTimestamp(row.original.normalizedAt)}
        </span>
      ),
    });

    dynamicCols.push({
      id: 'actions',
      header: '',
      cell: ({ row }) => renderActionsCell(row.original, row.id),
    });

    return dynamicCols;
  }, [records, entityName, outboundByTrace, expandedRowIds, onOpenTraceDetail, onSelectRecord]);

  const table = useReactTable({
    data: filteredRecords,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="space-y-3">
      {/* Search Bar */}
      <div className="flex items-center justify-between gap-4">
        <div className="relative w-80">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={`Search ${entityName.toLowerCase()}...`}
            className="pl-9 text-xs h-9 bg-card"
          />
        </div>
        <div className="text-xs text-muted-foreground">
          Showing <strong>{filteredRecords.length}</strong> {entityName.toLowerCase()}
        </div>
      </div>

      {/* Grid */}
      <div
        tabIndex={0}
        role="region"
        aria-label={`${entityName} table`}
        className="table-wrapper rounded-xl border border-border bg-card shadow-sm"
      >
        <Table>
          <TableHeader className="sticky top-0 bg-muted/90 backdrop-blur-sm z-10 border-b border-border">
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id} className="hover:bg-transparent border-0">
                {headerGroup.headers.map((header) => (
                  <TableHead
                    key={header.id}
                    className="font-semibold text-foreground text-xs py-3 px-4"
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="h-36 text-center text-xs text-muted-foreground"
                >
                  Loading {entityName.toLowerCase()}...
                </TableCell>
              </TableRow>
            ) : filteredRecords.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="h-36 text-center text-xs text-muted-foreground"
                >
                  No {entityName.toLowerCase()} found. Data synchronization will populate this
                  table.
                </TableCell>
              </TableRow>
            ) : (
              table.getRowModel().rows.map((row) => {
                const isExpanded = expandedRowIds.has(row.id);
                const outs = getOutboundsForRecord(row.original);

                return (
                  <React.Fragment key={row.id}>
                    <TableRow
                      onClick={() => toggleRowExpanded(row.id)}
                      className={`cursor-pointer transition-colors ${
                        isExpanded ? 'bg-muted/30' : 'hover:bg-muted/40'
                      }`}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id} className="py-2.5 px-4 align-middle">
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </TableCell>
                      ))}
                    </TableRow>

                    {/* Inline Expandable Sub-Row */}
                    {isExpanded && (
                      <TableRow className="bg-muted/15 border-b border-border hover:bg-muted/15">
                        <TableCell colSpan={columns.length} className="p-4 sm:p-5">
                          <RecordDetail
                            record={row.original}
                            entityName={singularName}
                            fallbackOutbound={outs[0]}
                            fallbackOutbounds={outs}
                            onOpenTraceDetail={onOpenTraceDetail}
                            onOpenTraceStitches={onOpenTraceStitches}
                          />
                        </TableCell>
                      </TableRow>
                    )}
                  </React.Fragment>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

// Deprecated alias for backward-compatibility during phase transition
export {
  RecordsTable as BusinessEntityDataTable,
  type RecordsTableProps as BusinessEntityDataTableProps,
};
