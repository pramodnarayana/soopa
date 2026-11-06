import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Skeleton,
  StatusBadge,
  StatusTone,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Tabs,
  TabsList,
  TabsTrigger,
} from '@soopa/ui';
import { type ColumnDef, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import {
  Cable,
  ChevronRight,
  Cloud,
  CreditCard,
  Globe,
  Layers,
  LayoutGrid,
  Plus,
  Search,
  Server,
  Trash2,
  Zap,
} from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { toast } from 'sonner';
import { useCatalogAppsQuery } from '../../application/use-catalog-queries';
import {
  useConnectionsQuery,
  useDeleteConnectionMutation,
} from '../../application/use-connection-queries';
import type { CatalogAppSummary } from '../../domain/catalog';
import { type Connection, groupActiveConnectionsByApp } from '../../domain/connection';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { IpPageHeader } from '../shared/IpPageHeader';
import { formatRelativeTimestamp, mapConnectionStatusTone } from '../shared/status-mapping';
import { CreateConnectionModal } from './CreateConnectionModal';

const MAIN_TAB_DIRECTORY = 'directory';
const MAIN_TAB_ACTIVE = 'active';

const CATEGORIES = [
  { label: 'All', value: '' },
  { label: 'API & REST', value: 'API' },
  { label: 'CRM', value: 'CRM' },
  { label: 'Billing', value: 'BILLING' },
  { label: 'Energy & AMI', value: 'ENERGY' },
  { label: 'ITSM', value: 'ITSM' },
  { label: 'Storage', value: 'STORAGE' },
] as const;

function getAppIcon(category?: string | null, appId?: string) {
  const cat = category?.toLowerCase();
  const id = appId?.toLowerCase();
  if (id === 'http' || cat === 'api') return <Globe className="h-5 w-5 text-brand-ink" />;
  if (id?.includes('stripe') || cat === 'billing')
    return <CreditCard className="h-5 w-5 text-status-healthy-fg" />;
  if (id?.includes('salesforce') || id?.includes('hubspot') || cat === 'crm')
    return <Cloud className="h-5 w-5 text-primary" />;
  if (id?.includes('sftp') || cat === 'storage')
    return <Server className="h-5 w-5 text-status-warning-fg" />;
  if (id?.includes('itron') || cat === 'energy') return <Zap className="h-5 w-5 text-brand-ink" />;
  return <Layers className="h-5 w-5 text-primary" />;
}

export interface IpConnectionsPageProps {
  readonly initialTab?: typeof MAIN_TAB_DIRECTORY | typeof MAIN_TAB_ACTIVE;
}

export function IpConnectionsPage({
  initialTab = MAIN_TAB_DIRECTORY,
}: IpConnectionsPageProps = {}) {
  const { navigation } = useIpWorkspace();
  const [mainTab, setMainTab] = useState<string>(initialTab);
  const [activeSearch, setActiveSearch] = useState('');
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [configuredApp, setConfiguredApp] = useState<CatalogAppSummary | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [connectionToDelete, setConnectionToDelete] = useState<Connection | null>(null);
  const deleteMutation = useDeleteConnectionMutation();

  // 1. Fetch catalog apps for the OpenAI-style plugin directory
  const catalogView = useCatalogAppsQuery({
    category: selectedCategory || undefined,
    search: search.trim() || undefined,
  });
  const apps = catalogView.data ?? [];

  // 2. Fetch all connections for badge count and active apps table
  const allConnectionsView = useConnectionsQuery();
  const connections = allConnectionsView.data ?? [];
  const connectionsByApp = useMemo(() => groupActiveConnectionsByApp(connections), [connections]);

  // 3. Filter connections for Active Apps tab
  const filteredConnections = useMemo<Connection[]>(() => {
    const q = activeSearch.trim().toLowerCase();
    if (!q) return [...connections];
    return connections.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        c.appId.toLowerCase().includes(q) ||
        c.status.toLowerCase().includes(q) ||
        c.authType.toLowerCase().includes(q),
    );
  }, [connections, activeSearch]);

  const handleConnectApp = (app: CatalogAppSummary) => {
    setConfiguredApp(app);
    setCreateOpen(true);
  };

  const columns = useMemo<ColumnDef<Connection>[]>(
    () => [
      {
        accessorKey: 'name',
        header: 'Connection',
        cell: ({ row }) => (
          <div>
            <div className="font-semibold text-foreground">{row.original.name}</div>
            <div className="font-mono text-xs text-muted-foreground">{row.original.appId}</div>
          </div>
        ),
      },
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => (
          <StatusBadge
            label={row.original.status}
            tone={mapConnectionStatusTone(row.original.status)}
          />
        ),
      },
      {
        accessorKey: 'authType',
        header: 'Auth Strategy',
        cell: ({ row }) => <StatusBadge label={row.original.authType} tone={StatusTone.NEUTRAL} />,
      },
      {
        accessorKey: 'tokenExpiresAt',
        header: 'Token Expiry',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground tabular-nums">
            {row.original.tokenExpiresAt
              ? formatRelativeTimestamp(row.original.tokenExpiresAt)
              : 'Non-expiring'}
          </span>
        ),
      },
      {
        accessorKey: 'updatedAt',
        header: 'Updated',
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground tabular-nums">
            {formatRelativeTimestamp(row.original.updatedAt)}
          </span>
        ),
      },
      {
        id: 'actions',
        size: 80,
        header: () => <span className="sr-only">Actions</span>,
        cell: ({ row }) => (
          <div
            className="flex items-center justify-end gap-1 pr-1"
            onClick={(e) => e.stopPropagation()}
          >
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground"
              onClick={(e) => {
                e.stopPropagation();
                navigation.toConnectionDetail(row.original.id);
              }}
              title={`View ${row.original.name} details`}
              aria-label={`View ${row.original.name} details`}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
              onClick={(e) => {
                e.stopPropagation();
                setConnectionToDelete(row.original);
              }}
              title={`Delete ${row.original.name}`}
              aria-label={`Delete ${row.original.name}`}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ),
      },
    ],
    [],
  );

  const handleConfirmDelete = async () => {
    if (!connectionToDelete) return;
    const res = await deleteMutation.mutateAsync(connectionToDelete.id);
    if (res.ok) {
      toast.success(
        `Connection "${connectionToDelete.name}" deleted. Historical entities and synced data preserved.`,
      );
      setConnectionToDelete(null);
    } else {
      toast.error(res.error.message || 'Failed to delete connection.');
    }
  };

  const table = useReactTable({
    data: filteredConnections,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="space-y-6">
      <IpPageHeader title="Apps" />

      <Tabs value={mainTab} onValueChange={setMainTab}>
        <TabsList>
          <TabsTrigger value={MAIN_TAB_DIRECTORY} className="gap-1.5">
            <LayoutGrid className="h-4 w-4" />
            <span>All Apps ({apps.length})</span>
          </TabsTrigger>
          <TabsTrigger value={MAIN_TAB_ACTIVE} className="gap-1.5">
            <Cable className="h-4 w-4" />
            <span>Active Apps ({connections.length})</span>
          </TabsTrigger>
        </TabsList>
      </Tabs>

      {mainTab === MAIN_TAB_DIRECTORY ? (
        <div className="space-y-5">
          {/* Search & Category Filter Toolbar */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative w-full max-w-md">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search apps by name, category, or protocol..."
                className="pl-9"
              />
            </div>

            <div className="flex flex-wrap gap-1.5">
              {CATEGORIES.map((cat) => {
                const isSelected = selectedCategory === cat.value;
                return (
                  <Button
                    key={cat.value}
                    type="button"
                    size="sm"
                    variant={isSelected ? 'default' : 'outline'}
                    onClick={() => setSelectedCategory(cat.value)}
                    className="h-8 rounded-lg text-xs"
                  >
                    {cat.label}
                  </Button>
                );
              })}
            </div>
          </div>

          <ApiProblemBanner
            problem={catalogView.problem}
            onRetry={() => void catalogView.refetch()}
          />

          {catalogView.isLoading ? (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-44 w-full rounded-2xl" />
              ))}
            </div>
          ) : apps.length === 0 ? (
            <div className="flex min-h-[240px] flex-col items-center justify-center rounded-2xl border border-dashed border-border p-8 text-center">
              <LayoutGrid className="h-8 w-8 text-muted-foreground" />
              <h3 className="mt-3 font-semibold text-foreground">No Apps Found</h3>
              <p className="mt-1 max-w-sm text-xs text-muted-foreground">
                No catalog connectors matched your search or category filter. Try clearing your
                filters.
              </p>
              {(search || selectedCategory) && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setSearch('');
                    setSelectedCategory('');
                  }}
                  className="mt-4"
                >
                  Clear Filters
                </Button>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {apps.map((app) => {
                const installedList = connectionsByApp.get(app.appId) ?? [];
                const isInstalled = installedList.length > 0;
                return (
                  <div
                    key={app.appId}
                    className="flex flex-col justify-between rounded-2xl border border-border bg-card p-5 shadow-xs transition-all hover:border-primary/50 hover:shadow-md"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-center gap-3">
                        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-border bg-muted/60">
                          {getAppIcon(app.category, app.appId)}
                        </div>
                        <div>
                          <h3 className="font-semibold text-foreground text-sm leading-tight">
                            {app.displayName}
                          </h3>
                          <span className="font-mono text-xs text-muted-foreground">
                            {app.category} · {app.appId}
                          </span>
                        </div>
                      </div>
                      {isInstalled ? (
                        <StatusBadge
                          label={`${installedList.length} Connected`}
                          tone={StatusTone.HEALTHY}
                        />
                      ) : null}
                    </div>

                    <div className="mt-5 flex items-center justify-between border-t border-border/60 pt-3">
                      <StatusBadge label={app.authType} tone={StatusTone.NEUTRAL} />
                      <Button
                        type="button"
                        size="sm"
                        variant={isInstalled ? 'outline' : 'default'}
                        onClick={() => handleConnectApp(app)}
                        className="gap-1.5 font-medium"
                      >
                        <Plus className="h-4 w-4" />
                        <span>{isInstalled ? 'Add Another' : 'Connect'}</span>
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          <ApiProblemBanner
            problem={allConnectionsView.problem}
            onRetry={() => void allConnectionsView.refetch()}
          />

          {/* Search and Action Toolbar */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative w-full max-w-sm">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={activeSearch}
                onChange={(e) => setActiveSearch(e.target.value)}
                placeholder="Search active apps by name, connector, or status..."
                className="h-9 pl-9 text-xs"
              />
            </div>
            <span className="text-xs text-muted-foreground tabular-nums">
              {filteredConnections.length} configured
            </span>
          </div>

          {/* EDI-Style Single-Border TanStack Table with Permanent TableHeader */}
          <div className="rounded-xl border border-border bg-card overflow-hidden">
            <Table>
              <TableHeader className="bg-muted/50 border-b border-border">
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id} className="hover:bg-transparent border-0">
                    {headerGroup.headers.map((header) => (
                      <TableHead
                        key={header.id}
                        style={header.id === 'actions' ? { width: 56 } : undefined}
                        className={`font-semibold text-foreground text-xs py-2.5 px-3 ${
                          header.id === 'actions' ? 'w-14 text-right' : ''
                        }`}
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
                {allConnectionsView.isLoading ? (
                  <TableRow>
                    <TableCell
                      colSpan={columns.length}
                      className="h-32 text-center text-xs text-muted-foreground"
                    >
                      Loading active apps...
                    </TableCell>
                  </TableRow>
                ) : filteredConnections.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={columns.length}
                      className="h-32 text-center text-xs text-muted-foreground"
                    >
                      No active apps configured. Explore All Apps to connect your first integration.
                    </TableCell>
                  </TableRow>
                ) : (
                  table.getRowModel().rows.map((row) => (
                    <TableRow
                      key={row.id}
                      tabIndex={0}
                      role="button"
                      className="cursor-pointer hover:bg-muted/50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          navigation.toConnectionDetail(row.original.id);
                        }
                      }}
                      onClick={() => navigation.toConnectionDetail(row.original.id)}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell
                          key={cell.id}
                          className={`py-2.5 px-3 align-middle ${
                            cell.column.id === 'actions' ? 'w-14 text-right' : ''
                          }`}
                        >
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </div>
      )}

      <CreateConnectionModal
        open={createOpen}
        onOpenChange={(open) => {
          setCreateOpen(open);
          if (!open) setConfiguredApp(null);
        }}
        initialApp={configuredApp}
        onCreated={(id) => navigation.toConnectionDetail(id)}
      />

      <Dialog
        open={connectionToDelete !== null}
        onOpenChange={(open) => {
          if (!open) setConnectionToDelete(null);
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete Connection</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete{' '}
              <span className="font-semibold text-foreground">{connectionToDelete?.name}</span>?
              Historical entities and synced data will remain preserved.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="mt-4 gap-2 sm:gap-0">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={deleteMutation.isPending}
              onClick={() => setConnectionToDelete(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              size="sm"
              disabled={deleteMutation.isPending}
              onClick={() => void handleConfirmDelete()}
            >
              {deleteMutation.isPending ? 'Deleting...' : 'Delete Connection'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
