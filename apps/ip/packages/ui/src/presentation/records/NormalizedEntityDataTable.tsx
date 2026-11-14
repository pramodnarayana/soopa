import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  MonacoCodeViewer,
  StatusBadge,
  StatusTone,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@soopa/ui';
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
} from '@tanstack/react-table';
import {
  ChevronLeft,
  ChevronRight,
  Code2,
  Database,
  GitFork,
  RefreshCw,
  Search,
} from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { useNormalizedRecordsQuery } from '../../application/use-record-queries';
import type { ConnectionEntityField } from '../../domain/connection-entity';
import type { NormalizedRecord } from '../../domain/trace';
import { formatRelativeTimestamp, stringifyJsonPretty } from '../shared/status-mapping';

export interface NormalizedEntityDataTableProps {
  readonly connectionId: string;
  readonly streamName: string;
  readonly fields?: readonly ConnectionEntityField[];
  readonly primaryKey?: readonly string[];
  readonly onOpenTrace?: (traceId: string) => void;
}

function formatHeaderLabel(key: string): string {
  return key
    .replace(/[._]/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bId\b/g, 'ID')
    .replace(/\bPk\b/gi, 'PK')
    .replace(/\bUrl\b/gi, 'URL')
    .trim();
}

function formatDateCompact(isoString: string): string {
  try {
    const d = new Date(isoString);
    if (Number.isNaN(d.getTime())) return isoString;
    return d.toISOString().replace('T', ' ').slice(0, 19);
  } catch {
    return isoString;
  }
}

const INTERNAL_METADATA_KEYS = new Set([
  'transformation_id',
  'transformation_version',
  'extensions',
  'canonical_id',
]);

export function isRecordMatchingStream(record: NormalizedRecord, streamName: string): boolean {
  if (!streamName) return true;
  const sNorm = streamName.toLowerCase().replace(/[^a-z0-9]/g, '');
  const cNorm = record.canonicalType.toLowerCase().replace(/[^a-z0-9]/g, '');
  if (!sNorm || !cNorm) return true;

  // 1. Direct equality or substring match
  if (sNorm === cNorm || cNorm.includes(sNorm) || sNorm.includes(cNorm)) {
    return true;
  }

  // 2. Singular stem match (handles plurals: entity_items vs CANONICAL_ENTITY_ITEM)
  const sStem = sNorm.replace(/s$/, '');
  const cStem = cNorm.replace(/s$/, '');
  if (
    sStem &&
    cStem &&
    (cNorm.includes(sStem) ||
      sNorm.includes(cStem) ||
      cStem.includes(sStem) ||
      sStem.includes(cStem))
  ) {
    return true;
  }

  // 3. Transformation ID match (e.g. "domain.entity_transform" contains "entity_transform")
  const transformId =
    record.canonicalData && typeof record.canonicalData === 'object'
      ? String(
          (record.canonicalData as Record<string, unknown>).transformation_id ?? '',
        ).toLowerCase()
      : '';
  if (transformId && (transformId.includes(sNorm) || (sStem && transformId.includes(sStem)))) {
    return true;
  }

  // 4. Source ID fallback
  if (
    record.sourceId &&
    (record.sourceId.toLowerCase().includes(sNorm) ||
      (sStem && record.sourceId.toLowerCase().includes(sStem)))
  ) {
    return true;
  }

  return false;
}

export function NormalizedEntityDataTable({
  connectionId,
  streamName,
  fields,
  primaryKey = [],
  onOpenTrace,
}: NormalizedEntityDataTableProps) {
  const [search, setSearch] = useState('');
  const [selectedRecordJson, setSelectedRecordJson] = useState<string | null>(null);
  const [selectedRecordTitle, setSelectedRecordTitle] = useState<string>('');

  const normalizedQuery = useNormalizedRecordsQuery({ connectionId, limit: 100 });

  // Filter records belonging to this specific stream
  const matchingRecords = useMemo<readonly NormalizedRecord[]>(() => {
    const allRecords = normalizedQuery.data ?? [];
    if (!allRecords.length) return [];

    return allRecords.filter((r) => isRecordMatchingStream(r, streamName));
  }, [normalizedQuery.data, streamName]);

  // Client-side search across all fields of the record
  const filteredRows = useMemo<NormalizedRecord[]>(() => {
    const query = search.trim().toLowerCase();
    if (!query) return [...matchingRecords];

    return matchingRecords.filter((record) => {
      if (record.sourceId.toLowerCase().includes(query)) return true;
      if (record.id.toLowerCase().includes(query)) return true;
      if (record.canonicalType.toLowerCase().includes(query)) return true;

      const dataObj = record.canonicalData;
      if (dataObj && typeof dataObj === 'object') {
        for (const val of Object.values(dataObj)) {
          if (val !== null && val !== undefined) {
            if (String(val).toLowerCase().includes(query)) return true;
          }
        }
      }
      return false;
    });
  }, [matchingRecords, search]);

  // Dynamic TanStack column definitions matching canonical attributes
  const columns = useMemo<ColumnDef<NormalizedRecord>[]>(() => {
    // 1. When normalized records exist, columns come strictly from canonicalData.
    // Fall back to schema fields only when the table is empty.
    const attributeKeys: string[] = [];
    if (matchingRecords.length > 0) {
      for (const record of matchingRecords) {
        if (record.canonicalData && typeof record.canonicalData === 'object') {
          for (const key of Object.keys(record.canonicalData)) {
            if (!INTERNAL_METADATA_KEYS.has(key) && !attributeKeys.includes(key)) {
              attributeKeys.push(key);
            }
          }
        }
      }
    } else if (fields && fields.length > 0) {
      for (const f of fields) {
        if (!attributeKeys.includes(f.name)) {
          attributeKeys.push(f.name);
        }
      }
    }

    if (attributeKeys.length === 0) {
      attributeKeys.push('source_id');
    }

    const pkNormalizedSet = new Set(primaryKey.map((k) => k.toLowerCase().replace(/[._]/g, '')));

    // Extract significant root tokens (length >= 3, excluding generic suffix 'id'/'key') for generic PK matching
    const pkSignificantTokenGroups: string[][] = primaryKey
      .map((pk) =>
        pk
          .toLowerCase()
          .split(/[^a-z0-9]+/)
          .filter((w) => w.length >= 3 && w !== 'id' && w !== 'key'),
      )
      .filter((group) => group.length > 0);

    const isPrimaryKey = (key: string): boolean => {
      const kNorm = key.toLowerCase().replace(/[._]/g, '');
      if (pkNormalizedSet.has(kNorm)) return true;
      if (
        pkNormalizedSet.has('id') &&
        (kNorm === 'id' || kNorm === 'sourceid' || kNorm === 'recordid')
      ) {
        return true;
      }
      const kLower = key.toLowerCase();
      for (const tokenGroup of pkSignificantTokenGroups) {
        if (tokenGroup.every((token) => kLower.includes(token))) {
          return true;
        }
      }
      return false;
    };

    // 2. Sort attribute keys so primary key column(s) ALWAYS appear first
    const sortedAttributeKeys = [...attributeKeys].sort((a, b) => {
      const aIsPk = isPrimaryKey(a);
      const bIsPk = isPrimaryKey(b);
      if (aIsPk && !bIsPk) return -1;
      if (!aIsPk && bIsPk) return 1;
      return 0;
    });

    // 3. Generate typed column definition for each canonical attribute
    const dynamicCols: ColumnDef<NormalizedRecord>[] = sortedAttributeKeys.map((key) => {
      const isPk = isPrimaryKey(key);
      const label = formatHeaderLabel(key);

      return {
        id: key,
        accessorFn: (row) => {
          if (
            key in row.canonicalData &&
            row.canonicalData[key] !== undefined &&
            row.canonicalData[key] !== null
          ) {
            return row.canonicalData[key];
          }
          if (key === 'source_id' || key === 'record_id') {
            return row.sourceId;
          }
          if (key === 'id') {
            return row.id;
          }
          if (key === 'trace_id' || key === 'traceId') {
            return row.traceId;
          }
          return null;
        },
        header: () => (
          <div className="flex items-center gap-1.5 font-semibold text-foreground">
            <span>{label}</span>
            {isPk ? (
              <span className="rounded bg-primary/10 px-1 py-0.5 text-[10px] font-mono font-medium text-primary">
                PK
              </span>
            ) : null}
          </div>
        ),
        cell: ({ getValue }) => {
          const val = getValue();
          if (val === null || val === undefined) {
            return <span className="text-muted-foreground font-mono text-xs">—</span>;
          }

          if (typeof val === 'boolean') {
            return (
              <StatusBadge
                label={val ? 'TRUE' : 'FALSE'}
                tone={val ? StatusTone.HEALTHY : StatusTone.NEUTRAL}
              />
            );
          }

          if (typeof val === 'number') {
            return (
              <span className="font-mono text-xs text-foreground tabular-nums">
                {val.toLocaleString(undefined, { maximumFractionDigits: 4 })}
              </span>
            );
          }

          if (typeof val === 'string') {
            if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(val)) {
              return (
                <span className="text-xs font-mono text-foreground">{formatDateCompact(val)}</span>
              );
            }
            return <span className="text-xs text-foreground">{val}</span>;
          }

          if (typeof val === 'object') {
            const rawJson = JSON.stringify(val);
            return (
              <span
                className="font-mono text-[11px] text-muted-foreground truncate max-w-[200px] block"
                title={rawJson}
              >
                {rawJson}
              </span>
            );
          }

          return <span className="text-xs text-foreground">{String(val)}</span>;
        },
      };
    });

    // 3. Add Normalized At audit column
    dynamicCols.push({
      accessorKey: 'normalizedAt',
      header: 'Synced At',
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground whitespace-nowrap">
          {formatRelativeTimestamp(row.original.normalizedAt)}
        </span>
      ),
    });

    // 4. Add Actions column (Inspect JSON & Trace)
    dynamicCols.push({
      id: 'actions',
      header: 'Actions',
      cell: ({ row }) => (
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              setSelectedRecordTitle(
                `${formatHeaderLabel(streamName)} Record (${row.original.sourceId})`,
              );
              setSelectedRecordJson(
                stringifyJsonPretty({
                  id: row.original.id,
                  source_id: row.original.sourceId,
                  canonical_type: row.original.canonicalType,
                  normalized_at: row.original.normalizedAt,
                  data: row.original.canonicalData,
                }),
              );
            }}
            className="h-7 px-2 gap-1 text-xs text-muted-foreground hover:text-foreground"
            title="Inspect raw JSON"
          >
            <Code2 className="h-3.5 w-3.5" />
            <span>JSON</span>
          </Button>

          {onOpenTrace ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onOpenTrace(row.original.traceId)}
              className="h-7 px-2 gap-1 text-xs text-muted-foreground hover:text-foreground"
              title={`View pipeline trace ${row.original.traceId}`}
            >
              <GitFork className="h-3.5 w-3.5" />
              <span>Trace</span>
            </Button>
          ) : null}
        </div>
      ),
    });

    return dynamicCols;
  }, [fields, primaryKey, matchingRecords, streamName, onOpenTrace]);

  const table = useReactTable({
    data: filteredRows,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: {
      pagination: {
        pageSize: 15,
      },
    },
  });

  return (
    <div className="space-y-3">
      {/* Table Toolbar: Entity Name, Total Count, Search and Refresh */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-1">
        <div className="flex items-center gap-2.5">
          <Database className="h-4 w-4 text-primary shrink-0" />
          <span className="font-semibold text-xs text-foreground uppercase tracking-wide">
            {formatHeaderLabel(streamName)}
          </span>
          <span className="rounded-full bg-muted/80 border border-border px-2 py-0.5 text-[11px] font-mono font-medium text-muted-foreground tabular-nums">
            Showing {filteredRows.length.toLocaleString()}{' '}
            {filteredRows.length === 1 ? 'record' : 'records'} (recent preview, max 100)
          </span>
        </div>

        <div className="flex items-center gap-2">
          <div className="relative w-64">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search in records..."
              className="h-8 pl-8 text-xs font-mono rounded-lg"
              aria-label={`Search ${streamName} records`}
            />
          </div>

          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void normalizedQuery.refetch()}
            disabled={normalizedQuery.isLoading}
            className="h-8 w-8 p-0"
            title="Refresh records"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${normalizedQuery.isLoading ? 'animate-spin' : ''}`}
            />
          </Button>
        </div>
      </div>

      {/* Accessible TanStack Data Table */}
      <div
        tabIndex={0}
        role="region"
        aria-label={`${streamName} records table`}
        className="table-wrapper rounded-xl border border-border bg-card overflow-auto max-h-[440px] [&_[data-slot=table-container]]:overflow-visible"
      >
        <Table>
          <TableHeader className="sticky top-0 bg-muted/90 backdrop-blur-sm z-10 border-b border-border">
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id} className="hover:bg-transparent border-0">
                {headerGroup.headers.map((header) => (
                  <TableHead
                    key={header.id}
                    scope="col"
                    className="font-semibold text-foreground text-xs py-2 px-3 whitespace-nowrap"
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
            {normalizedQuery.isLoading ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="h-32 text-center text-xs text-muted-foreground"
                >
                  Loading {formatHeaderLabel(streamName)} records...
                </TableCell>
              </TableRow>
            ) : normalizedQuery.problem ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="h-32 text-center text-xs text-destructive space-y-2 py-6"
                >
                  <p className="font-medium">
                    Failed to load records:{' '}
                    {normalizedQuery.problem.message || normalizedQuery.problem.code}
                  </p>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => void normalizedQuery.refetch()}
                    className="h-7 text-xs mt-2"
                  >
                    Retry
                  </Button>
                </TableCell>
              </TableRow>
            ) : filteredRows.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="h-32 text-center text-xs text-muted-foreground"
                >
                  {search.trim()
                    ? `No records matching "${search}".`
                    : `No normalized records found for "${streamName}". Run a sync to populate records.`}
                </TableCell>
              </TableRow>
            ) : (
              table.getRowModel().rows.map((row) => (
                <TableRow key={row.id} className="hover:bg-muted/40 transition-colors">
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id} className="py-2 px-3 align-middle whitespace-nowrap">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Pagination Controls */}
      {table.getPageCount() > 1 && (
        <div className="flex items-center justify-between px-2 pt-1 text-xs text-muted-foreground">
          <span>
            Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}
          </span>
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
              className="h-7 px-2"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
              <span>Previous</span>
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
              className="h-7 px-2"
            >
              <span>Next</span>
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}

      {/* Slide-Down Raw JSON Inspector (for power users) */}
      {selectedRecordJson && (
        <Card className="border border-border bg-card/95 shadow-md">
          <CardHeader className="flex flex-row items-center justify-between pb-2 pt-3 px-4">
            <div>
              <CardTitle className="text-xs font-semibold">{selectedRecordTitle}</CardTitle>
              <CardDescription className="text-[11px]">
                Raw canonical JSON record attributes.
              </CardDescription>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setSelectedRecordJson(null)}
              className="h-7 px-2 text-xs"
            >
              Close
            </Button>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            <MonacoCodeViewer value={selectedRecordJson} language="json" height="260px" />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
