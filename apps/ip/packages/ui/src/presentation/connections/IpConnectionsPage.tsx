import {
  Button,
  CopyableIdPill,
  DataTable,
  Input,
  Skeleton,
  StatusBadge,
  StatusTone,
  Tabs,
  TabsList,
  TabsTrigger,
} from '@soopa/ui';
import { type ColumnDef, getCoreRowModel, useReactTable } from '@tanstack/react-table';
import {
  Cable,
  Cloud,
  CreditCard,
  Globe,
  Layers,
  LayoutGrid,
  Plus,
  Search,
  Server,
  Zap,
} from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { useCatalogAppsQuery } from '../../application/use-catalog-queries';
import { useConnectionsQuery } from '../../application/use-connection-queries';
import type { CatalogAppSummary } from '../../domain/catalog';
import type { Connection } from '../../domain/connection';
import { ConnectionStatus } from '../../domain/enums';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { IpPageHeader } from '../shared/IpPageHeader';
import { formatRelativeTimestamp, mapConnectionStatusTone } from '../shared/status-mapping';
import { CreateConnectionModal } from './CreateConnectionModal';

const ALL_TAB = 'ALL';
const MAIN_TAB_DIRECTORY = 'directory';
const MAIN_TAB_INSTALLED = 'installed';

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

export function IpConnectionsPage() {
  const { navigation } = useIpWorkspace();
  const [mainTab, setMainTab] = useState<string>(MAIN_TAB_DIRECTORY);
  const [statusTab, setStatusTab] = useState<string>(ALL_TAB);
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [configuredApp, setConfiguredApp] = useState<CatalogAppSummary | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  // 1. Fetch catalog apps for the OpenAI-style plugin directory
  const catalogView = useCatalogAppsQuery({
    category: selectedCategory || undefined,
    search: search.trim() || undefined,
  });
  const apps = catalogView.data ?? [];

  // 2. Fetch all connections to display active counts on app cards
  const allConnectionsView = useConnectionsQuery();
  const connectionsByApp = useMemo(() => {
    const map = new Map<string, Connection[]>();
    for (const conn of allConnectionsView.data ?? []) {
      const list = map.get(conn.appId) ?? [];
      list.push(conn);
      map.set(conn.appId, list);
    }
    return map;
  }, [allConnectionsView.data]);

  // 3. Filtered connections for the Installed tab
  const filteredConnectionsView = useConnectionsQuery(
    statusTab === ALL_TAB ? undefined : statusTab,
  );
  const rows = useMemo(
    () => [...(filteredConnectionsView.data ?? [])],
    [filteredConnectionsView.data],
  );

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
        accessorKey: 'authType',
        header: 'Auth Strategy',
        cell: ({ row }) => <StatusBadge label={row.original.authType} tone={StatusTone.NEUTRAL} />,
      },
      {
        accessorKey: 'connectionFingerprint',
        header: 'SHA-256 Fingerprint',
        cell: ({ row }) => (
          <CopyableIdPill value={row.original.connectionFingerprint} truncateLength={16} />
        ),
      },
      {
        accessorKey: 'status',
        header: 'Health',
        cell: ({ row }) => (
          <StatusBadge
            label={row.original.status}
            tone={mapConnectionStatusTone(row.original.status)}
          />
        ),
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
    ],
    [],
  );

  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="space-y-6">
      <IpPageHeader
        eyebrow="Marketplace & Integration Hub"
        title="Apps & Connectors"
        subtitle="Explore pre-built enterprise apps and universal HTTP API protocols. Connect apps directly to run automated data ingestion, syncs, and stitches."
      />

      <Tabs value={mainTab} onValueChange={setMainTab}>
        <TabsList>
          <TabsTrigger value={MAIN_TAB_DIRECTORY} className="gap-1.5">
            <LayoutGrid className="h-4 w-4" />
            <span>All Apps ({apps.length})</span>
          </TabsTrigger>
          <TabsTrigger value={MAIN_TAB_INSTALLED} className="gap-1.5">
            <Cable className="h-4 w-4" />
            <span>Installed Apps ({allConnectionsView.data?.length ?? 0})</span>
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
                    <div className="space-y-3">
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

                      <p className="line-clamp-2 text-xs text-muted-foreground leading-relaxed">
                        {app.description ||
                          'Verified enterprise connector with live pre-flight checks.'}
                      </p>

                      {isInstalled ? (
                        <div className="mt-2 space-y-1.5 rounded-xl border border-border/60 bg-muted/30 p-2.5">
                          <span className="text-[11px] font-medium text-muted-foreground">
                            Active Connections:
                          </span>
                          <div className="flex flex-wrap gap-1.5">
                            {installedList.map((conn) => (
                              <button
                                key={conn.id}
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  navigation.toConnectionDetail(conn.id);
                                }}
                                className="inline-flex items-center gap-1.5 rounded-lg border border-border/80 bg-background px-2 py-1 text-xs font-medium text-foreground hover:border-primary hover:text-primary transition-colors"
                              >
                                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                                <span>{conn.name}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </div>

                    <div className="mt-4 flex items-center justify-between border-t border-border/60 pt-3">
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
            problem={filteredConnectionsView.problem}
            onRetry={() => void filteredConnectionsView.refetch()}
          />

          <Tabs value={statusTab} onValueChange={setStatusTab}>
            <TabsList>
              <TabsTrigger value={ALL_TAB}>All</TabsTrigger>
              <TabsTrigger value={ConnectionStatus.ACTIVE}>Active</TabsTrigger>
              <TabsTrigger value={ConnectionStatus.AUTH_EXPIRED}>Auth Expired</TabsTrigger>
              <TabsTrigger value={ConnectionStatus.DISCONNECTED}>Disconnected</TabsTrigger>
              <TabsTrigger value={ConnectionStatus.DEACTIVATED}>Deactivated</TabsTrigger>
            </TabsList>
          </Tabs>

          <DataTable
            table={table}
            columnsLength={columns.length}
            isLoading={filteredConnectionsView.isLoading}
            dataLength={rows.length}
            ariaLabel="Tenant integration connections"
            emptyIcon={<Cable className="h-6 w-6" />}
            emptyTitle="No Connections Configured"
            emptyDescription="Explore the All Apps directory to connect your first integration."
            onRowClick={(row) => navigation.toConnectionDetail(row.original.id)}
          />
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
    </div>
  );
}
