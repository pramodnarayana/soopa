import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  CopyableIdPill,
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
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@soopa/ui';
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  type Table as ReactTable,
  useReactTable,
} from '@tanstack/react-table';
import {
  ArrowRightLeft,
  Database,
  FileCode2,
  Layers,
  Lock,
  Radio,
  Search,
  Shield,
} from 'lucide-react';
import React, { useMemo, useState } from 'react';
import {
  useGemRecordsQuery,
  useInboundRecordsQuery,
  useNormalizedRecordsQuery,
  useReplicaRecordsQuery,
} from '../../application/use-record-queries';
import { useRecentTracesQuery } from '../../application/use-trace-queries';
import { IpUserRoleEnum } from '../../domain/role';
import type {
  GlobalEntityMapEntry,
  InboundRecord,
  NormalizedRecord,
  ReplicaRecord,
} from '../../domain/trace';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import {
  formatBytesCompact,
  formatRelativeTimestamp,
  stringifyJsonPretty,
} from '../shared/status-mapping';

interface PermanentRecordTableProps<TData> {
  readonly table: ReactTable<TData>;
  readonly columnsCount: number;
  readonly isLoading: boolean;
  readonly dataLength: number;
  readonly loadingMessage: string;
  readonly emptyMessage: string;
}

function PermanentRecordTable<TData>({
  table,
  columnsCount,
  isLoading,
  dataLength,
  loadingMessage,
  emptyMessage,
}: PermanentRecordTableProps<TData>) {
  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <Table>
        <TableHeader className="bg-muted/50 border-b border-border">
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id} className="hover:bg-transparent border-0">
              {headerGroup.headers.map((header) => (
                <TableHead
                  key={header.id}
                  className="font-semibold text-foreground text-xs py-2.5 px-3"
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
                colSpan={columnsCount}
                className="h-32 text-center text-xs text-muted-foreground"
              >
                {loadingMessage}
              </TableCell>
            </TableRow>
          ) : dataLength === 0 ? (
            <TableRow>
              <TableCell
                colSpan={columnsCount}
                className="h-32 text-center text-xs text-muted-foreground"
              >
                {emptyMessage}
              </TableCell>
            </TableRow>
          ) : (
            table.getRowModel().rows.map((row) => (
              <TableRow key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id} className="py-2 px-3 align-middle">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}

export interface SyncedDataInspectionPanelProps {
  readonly connectionId?: string;
  readonly initialEntityFilter?: string | null;
  readonly onOpenTrace?: (traceId: string) => void;
}

export function SyncedDataInspectionPanel({
  connectionId,
  initialEntityFilter,
  onOpenTrace,
}: SyncedDataInspectionPanelProps) {
  const { userRole } = useIpWorkspace();
  const [activeTab, setActiveTab] = useState<string>('l3');
  const [selectedRecordJson, setSelectedRecordJson] = useState<string | null>(null);
  const [selectedRecordTitle, setSelectedRecordTitle] = useState<string>('');
  const [searchFilter, setSearchFilter] = useState(initialEntityFilter ?? '');

  React.useEffect(() => {
    if (initialEntityFilter) {
      setSearchFilter(initialEntityFilter);
    }
  }, [initialEntityFilter]);

  const isCustomerRole = userRole === IpUserRoleEnum.CUSTOMER;

  // L3 Normalized records (Open to all roles)
  const normalizedQuery = useNormalizedRecordsQuery(
    { connectionId, limit: 100 },
    Boolean(activeTab === 'l3'),
  );

  // GEM identity links (Open to all roles)
  const gemQuery = useGemRecordsQuery(
    { sourceConnectionId: connectionId, limit: 100 },
    Boolean(activeTab === 'gem'),
  );

  // L2 Replica staging (Restricted to Support)
  const replicaQuery = useReplicaRecordsQuery(
    { connectionId, limit: 100 },
    Boolean(activeTab === 'l2' && !isCustomerRole),
  );

  // L1 Inbound wire (Restricted to Support)
  const inboundQuery = useInboundRecordsQuery(
    { connectionId, limit: 100, hydratePayloads: true },
    Boolean(activeTab === 'l1' && !isCustomerRole),
  );

  // Traces activity
  const tracesQuery = useRecentTracesQuery({ limit: 50 }, Boolean(activeTab === 'traces'));

  // Filtered Normalized Records
  const normalizedRows = useMemo<NormalizedRecord[]>(() => {
    const data = normalizedQuery.data ?? [];
    if (!searchFilter.trim()) return [...data];
    const term = searchFilter.toLowerCase().trim();
    return data.filter(
      (r) =>
        r.canonicalType.toLowerCase().includes(term) ||
        r.sourceId.toLowerCase().includes(term) ||
        r.id.toLowerCase().includes(term),
    );
  }, [normalizedQuery.data, searchFilter]);

  // Filtered GEM Entries
  const gemRows = useMemo<GlobalEntityMapEntry[]>(() => {
    const data = gemQuery.data ?? [];
    if (!searchFilter.trim()) return [...data];
    const term = searchFilter.toLowerCase().trim();
    return data.filter(
      (e) =>
        e.entityDomain.toLowerCase().includes(term) ||
        e.canonicalId.toLowerCase().includes(term) ||
        e.sourceEntityId.toLowerCase().includes(term) ||
        (e.destEntityId && e.destEntityId.toLowerCase().includes(term)),
    );
  }, [gemQuery.data, searchFilter]);

  // Filtered Replica Records (Item 48, 50)
  const replicaRows = useMemo<ReplicaRecord[]>(() => {
    const data = replicaQuery.data ?? [];
    if (!searchFilter.trim()) return [...data];
    const term = searchFilter.toLowerCase().trim();
    return data.filter(
      (r) =>
        r.stream.toLowerCase().includes(term) ||
        r.recordKey.toLowerCase().includes(term) ||
        r.id.toLowerCase().includes(term),
    );
  }, [replicaQuery.data, searchFilter]);

  // Filtered Inbound Records (Item 48, 50)
  const inboundRows = useMemo<InboundRecord[]>(() => {
    const data = inboundQuery.data ?? [];
    if (!searchFilter.trim()) return [...data];
    const term = searchFilter.toLowerCase().trim();
    return data.filter(
      (r) =>
        r.streamName.toLowerCase().includes(term) ||
        r.traceId.toLowerCase().includes(term) ||
        r.id.toLowerCase().includes(term),
    );
  }, [inboundQuery.data, searchFilter]);

  // Table Columns for L3 Normalized Table
  const normalizedColumns = useMemo<ColumnDef<NormalizedRecord>[]>(
    () => [
      {
        accessorKey: 'canonicalType',
        header: 'Canonical Entity',
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <span className="font-semibold text-foreground">{row.original.canonicalType}</span>
            <CopyableIdPill value={row.original.id} prefixLabel="L3 ID" />
          </div>
        ),
      },
      {
        accessorKey: 'sourceId',
        header: 'Source Identifier',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-foreground">{row.original.sourceId}</span>
        ),
      },
      {
        accessorKey: 'normalizedAt',
        header: 'Normalized At',
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">
            {formatRelativeTimestamp(row.original.normalizedAt)}
          </span>
        ),
      },
      {
        id: 'actions',
        header: 'Payload',
        cell: ({ row }) => (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setSelectedRecordTitle(
                `Canonical Record: ${row.original.canonicalType} (${row.original.sourceId})`,
              );
              setSelectedRecordJson(stringifyJsonPretty(row.original.canonicalData));
            }}
            className="gap-1.5"
          >
            <FileCode2 className="h-3.5 w-3.5" />
            <span>Inspect JSON</span>
          </Button>
        ),
      },
    ],
    [],
  );

  // Table Columns for GEM Table
  const gemColumns = useMemo<ColumnDef<GlobalEntityMapEntry>[]>(
    () => [
      {
        accessorKey: 'entityDomain',
        header: 'Domain',
        cell: ({ row }) => (
          <StatusBadge label={row.original.entityDomain} tone={StatusTone.HEALTHY} />
        ),
      },
      {
        accessorKey: 'sourceEntityId',
        header: 'Source ID',
        cell: ({ row }) => (
          <div className="flex flex-col">
            <span className="font-mono text-xs text-foreground">{row.original.sourceEntityId}</span>
            <span className="text-[10px] text-muted-foreground">
              {row.original.sourceConnectionId}
            </span>
          </div>
        ),
      },
      {
        id: 'crosswalk',
        header: 'Identity Crosswalk',
        cell: ({ row }) => (
          <div className="flex items-center gap-1.5 font-mono text-xs text-brand-ink">
            <ArrowRightLeft className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="font-semibold text-foreground">{row.original.canonicalId}</span>
          </div>
        ),
      },
      {
        accessorKey: 'destEntityId',
        header: 'Destination Link',
        cell: ({ row }) =>
          row.original.destEntityId ? (
            <span className="font-mono text-xs text-muted-foreground">
              {row.original.destEntityId}
            </span>
          ) : (
            <span className="text-xs italic text-muted-foreground">Pending Target Sync</span>
          ),
      },
      {
        accessorKey: 'createdAt',
        header: 'Created',
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">
            {formatRelativeTimestamp(row.original.createdAt)}
          </span>
        ),
      },
    ],
    [],
  );

  // Table Columns for L2 Replica Table
  const replicaColumns = useMemo<ColumnDef<ReplicaRecord>[]>(
    () => [
      {
        accessorKey: 'stream',
        header: 'Stream',
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <span className="font-semibold text-foreground">{row.original.stream}</span>
            <CopyableIdPill value={row.original.id} prefixLabel="L2 ID" />
          </div>
        ),
      },
      {
        accessorKey: 'recordKey',
        header: 'Record Key',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-foreground">{row.original.recordKey}</span>
        ),
      },
      {
        accessorKey: 'generationId',
        header: 'Gen / Version',
        cell: ({ row }) => (
          <span className="text-xs font-mono">
            Gen {row.original.generationId} · v{row.original.version}
          </span>
        ),
      },
      {
        accessorKey: 'extractedAt',
        header: 'Extracted',
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">
            {formatRelativeTimestamp(row.original.extractedAt)}
          </span>
        ),
      },
      {
        id: 'actions',
        header: 'Payload',
        cell: ({ row }) => (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setSelectedRecordTitle(
                `Replica Staging Record: ${row.original.stream} (${row.original.recordKey})`,
              );
              setSelectedRecordJson(stringifyJsonPretty(row.original.data));
            }}
            className="gap-1.5"
          >
            <FileCode2 className="h-3.5 w-3.5" />
            <span>Inspect Staging</span>
          </Button>
        ),
      },
    ],
    [],
  );

  // Table Columns for L1 Inbound Table
  const inboundColumns = useMemo<ColumnDef<InboundRecord>[]>(
    () => [
      {
        accessorKey: 'streamName',
        header: 'Stream Name',
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <span className="font-semibold text-foreground">{row.original.streamName}</span>
            <CopyableIdPill value={row.original.id} prefixLabel="L1 ID" />
          </div>
        ),
      },
      {
        accessorKey: 'ingestionMode',
        header: 'Ingestion Mode',
        cell: ({ row }) => (
          <StatusBadge label={row.original.ingestionMode} tone={StatusTone.NEUTRAL} />
        ),
      },
      {
        accessorKey: 'requestSizeBytes',
        header: 'Payload Size',
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">
            {formatBytesCompact(row.original.requestSizeBytes)}
          </span>
        ),
      },
      {
        accessorKey: 'receivedAt',
        header: 'Received At',
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">
            {formatRelativeTimestamp(row.original.receivedAt)}
          </span>
        ),
      },
      {
        id: 'actions',
        header: 'Wire Body',
        cell: ({ row }) => (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setSelectedRecordTitle(`L1 Inbound Wire Record: ${row.original.streamName}`);
              setSelectedRecordJson(
                stringifyJsonPretty(
                  row.original.requestBody ?? {
                    message: 'Body offloaded to S3',
                    s3Key: row.original.requestS3Key,
                  },
                ),
              );
            }}
            className="gap-1.5"
          >
            <FileCode2 className="h-3.5 w-3.5" />
            <span>Inspect Raw Wire</span>
          </Button>
        ),
      },
    ],
    [],
  );

  const normalizedTable = useReactTable({
    data: normalizedRows,
    columns: normalizedColumns,
    getCoreRowModel: getCoreRowModel(),
  });

  const gemTable = useReactTable({
    data: gemRows,
    columns: gemColumns,
    getCoreRowModel: getCoreRowModel(),
  });

  const replicaTable = useReactTable({
    data: replicaRows,
    columns: replicaColumns,
    getCoreRowModel: getCoreRowModel(),
  });

  const inboundTable = useReactTable({
    data: inboundRows,
    columns: inboundColumns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="space-y-6">
      {/* Role-Based Visibility Banner */}
      <Card className="border border-border bg-card/60">
        <CardContent className="flex flex-wrap items-center justify-between gap-4 p-4">
          <div className="flex items-center gap-3">
            <div
              className={`flex h-10 w-10 items-center justify-center rounded-xl ${isCustomerRole ? 'bg-status-warning-bg text-status-warning-fg' : 'bg-status-healthy-bg text-status-healthy-fg'}`}
            >
              {isCustomerRole ? <Lock className="h-5 w-5" /> : <Shield className="h-5 w-5" />}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-semibold text-foreground">
                  Current View:{' '}
                  {isCustomerRole ? 'Customer (Restricted)' : 'Customer Support (Full Diagnostic)'}
                </span>
                <StatusBadge
                  label={userRole.toUpperCase()}
                  tone={isCustomerRole ? StatusTone.WARNING : StatusTone.HEALTHY}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                {isCustomerRole
                  ? 'Restricted View: You can only view Layer 3 Normalized Records, GEM identity crosswalks, and Execution Traces. Raw wire (L1) and replica staging (L2) are strictly hidden.'
                  : 'Full View: Customer Support has permission to inspect all layers including Raw Wire Inbound (L1), Universal Replica (L2), Normalized (L3), GEM, and Traces.'}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Main Tabbed Record Viewer */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <TabsList>
            <TabsTrigger value="l3" className="gap-2">
              <Database className="h-4 w-4" />
              <span>L3: Normalized Canonical</span>
            </TabsTrigger>
            <TabsTrigger value="gem" className="gap-2">
              <ArrowRightLeft className="h-4 w-4" />
              <span>GEM: Identity Map</span>
            </TabsTrigger>
            {!isCustomerRole && (
              <>
                <TabsTrigger value="l2" className="gap-2">
                  <Layers className="h-4 w-4" />
                  <span>L2: Staging Replica</span>
                </TabsTrigger>
                <TabsTrigger value="l1" className="gap-2">
                  <Radio className="h-4 w-4" />
                  <span>L1: Raw Wire Inbound</span>
                </TabsTrigger>
              </>
            )}
            <TabsTrigger value="traces" className="gap-2">
              <FileCode2 className="h-4 w-4" />
              <span>Activity & Traces</span>
            </TabsTrigger>
          </TabsList>

          <div className="relative w-72">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
              placeholder="Search records or identifiers..."
              className="pl-9 text-xs"
            />
          </div>
        </div>

        {/* Tab 1: Layer 3 Normalized Records */}
        <TabsContent value="l3" className="pt-4 space-y-4">
          <ApiProblemBanner
            problem={normalizedQuery.problem}
            onRetry={() => void normalizedQuery.refetch()}
          />
          <PermanentRecordTable<NormalizedRecord>
            table={normalizedTable}
            columnsCount={normalizedColumns.length}
            isLoading={normalizedQuery.isLoading}
            dataLength={normalizedRows.length}
            loadingMessage="Loading canonical records..."
            emptyMessage="No normalized canonical records found. Trigger a sync to populate this table."
          />
        </TabsContent>

        {/* Tab 2: GEM Identity Crosswalk */}
        <TabsContent value="gem" className="pt-4 space-y-4">
          <ApiProblemBanner problem={gemQuery.problem} onRetry={() => void gemQuery.refetch()} />
          <PermanentRecordTable<GlobalEntityMapEntry>
            table={gemTable}
            columnsCount={gemColumns.length}
            isLoading={gemQuery.isLoading}
            dataLength={gemRows.length}
            loadingMessage="Loading Global Entity Map links..."
            emptyMessage="No Global Entity Map links discovered yet."
          />
        </TabsContent>

        {/* Tab 3: Layer 2 Replica Records (Support Only) */}
        {!isCustomerRole && (
          <TabsContent value="l2" className="pt-4 space-y-4">
            <ApiProblemBanner
              problem={replicaQuery.problem}
              onRetry={() => void replicaQuery.refetch()}
            />
            <PermanentRecordTable<ReplicaRecord>
              table={replicaTable}
              columnsCount={replicaColumns.length}
              isLoading={replicaQuery.isLoading}
              dataLength={(replicaQuery.data ?? []).length}
              loadingMessage="Loading staging replica snapshots..."
              emptyMessage="No staging replica snapshots found."
            />
          </TabsContent>
        )}

        {/* Tab 4: Layer 1 Inbound Wire Records (Support Only) */}
        {!isCustomerRole && (
          <TabsContent value="l1" className="pt-4 space-y-4">
            <ApiProblemBanner
              problem={inboundQuery.problem}
              onRetry={() => void inboundQuery.refetch()}
            />
            <PermanentRecordTable<InboundRecord>
              table={inboundTable}
              columnsCount={inboundColumns.length}
              isLoading={inboundQuery.isLoading}
              dataLength={(inboundQuery.data ?? []).length}
              loadingMessage="Loading inbound wire payloads..."
              emptyMessage="No raw inbound wire payloads received."
            />
          </TabsContent>
        )}

        {/* Tab 5: Traces & Waterfalls */}
        <TabsContent value="traces" className="pt-4 space-y-4">
          <div className="space-y-3">
            {(tracesQuery.data ?? []).slice(0, 10).map((trace) => (
              <div
                key={trace.traceId}
                className="flex items-center justify-between rounded-xl border border-border bg-card p-3.5 transition-colors hover:border-primary/50"
              >
                <div className="flex items-center gap-3">
                  <StatusBadge
                    label={trace.status}
                    tone={trace.status === 'SUCCEEDED' ? StatusTone.HEALTHY : StatusTone.WARNING}
                  />
                  <div className="flex flex-col">
                    <span className="font-mono text-xs font-semibold text-foreground">
                      Trace: {trace.traceId}
                    </span>
                    <span className="text-[10px] text-muted-foreground">
                      {formatRelativeTimestamp(trace.createdAt)} · Layer: {trace.primaryLayer}
                    </span>
                  </div>
                </div>
                {onOpenTrace && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => onOpenTrace(trace.traceId)}
                  >
                    Open Waterfall
                  </Button>
                )}
              </div>
            ))}
          </div>
        </TabsContent>
      </Tabs>

      {/* JSON Payload Inspector Drawer / Panel */}
      {selectedRecordJson && (
        <Card className="border border-border bg-card shadow-lg">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <div>
              <CardTitle className="text-sm font-semibold">{selectedRecordTitle}</CardTitle>
              <CardDescription className="text-xs">
                Inspect structured JSON attributes and canonical mappings.
              </CardDescription>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setSelectedRecordJson(null)}
            >
              Close
            </Button>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            <MonacoCodeViewer value={selectedRecordJson} language="json" height="320px" />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
