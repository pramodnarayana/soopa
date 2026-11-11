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
  Tabs,
  TabsList,
  TabsTrigger,
} from '@soopa/ui';
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
import { toast } from 'sonner';
import { useCatalogAppsQuery } from '../../application/use-catalog-queries';
import {
  useConnectionsQuery,
  useDeleteConnectionMutation,
} from '../../application/use-connection-queries';
import type { CatalogAppSummary } from '../../domain/catalog';
import { type Connection, groupActiveConnectionsByApp } from '../../domain/connection';
import { CatalogAppCategory, ConnectorRuntimeArchitecture } from '../../domain/enums';
import { useIpWorkspace } from '../../provider/IpRepositoriesContext';
import { ApiProblemBanner } from '../shared/ApiProblemBanner';
import { IpPageHeader } from '../shared/IpPageHeader';
import { ActiveConnectionCard } from './ActiveConnectionCard';
import { CreateConnectionModal } from './CreateConnectionModal';

const MAIN_TAB_DIRECTORY = 'directory';
const MAIN_TAB_ACTIVE = 'active';

const CATEGORY_LABELS: Readonly<Record<string, string>> = {
  API: 'API & REST',
  BILLING: 'Billing',
  CRM: 'CRM',
  ERP: 'ERP',
  ITSM: 'ITSM',
  SANDBOX: 'Sandbox',
  STORAGE: 'Storage',
};

function formatCategoryLabel(rawCategory: string): string {
  const normalized = rawCategory.trim().toUpperCase();
  const known = CATEGORY_LABELS[normalized];
  if (known) {
    return known;
  }
  return normalized
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(' ');
}

function deriveCategoryPills(
  apps: readonly CatalogAppSummary[],
): ReadonlyArray<{ readonly label: string; readonly value: string }> {
  const seen = new Set<string>();
  const dynamicPills: Array<{ readonly label: string; readonly value: string }> = [];
  for (const app of apps) {
    const raw = app.category.trim();
    if (!raw) continue;
    const upper = raw.toUpperCase();
    if (seen.has(upper)) continue;
    seen.add(upper);
    dynamicPills.push({ label: formatCategoryLabel(raw), value: raw });
  }
  dynamicPills.sort((a, b) => a.label.localeCompare(b.label));
  return [{ label: 'All', value: '' }, ...dynamicPills];
}

function getAppIcon(category?: string | null, runtimeArchitecture?: string | null) {
  const cat = category?.toUpperCase();
  const arch = runtimeArchitecture?.toUpperCase();
  if (cat === CatalogAppCategory.API || arch === ConnectorRuntimeArchitecture.GENERIC_HTTP)
    return <Globe className="h-5 w-5 text-brand-ink" />;
  if (cat === CatalogAppCategory.BILLING)
    return <CreditCard className="h-5 w-5 text-status-healthy-fg" />;
  if (cat === CatalogAppCategory.CRM) return <Cloud className="h-5 w-5 text-primary" />;
  if (cat === CatalogAppCategory.STORAGE || arch === ConnectorRuntimeArchitecture.NATIVE_PROTOCOL)
    return <Server className="h-5 w-5 text-status-warning-fg" />;
  if (cat === CatalogAppCategory.SANDBOX || arch === ConnectorRuntimeArchitecture.NATIVE_SIMULATOR)
    return <Zap className="h-5 w-5 text-brand-ink" />;
  return <Layers className="h-5 w-5 text-primary" />;
}

export interface IpConnectionsPageProps {
  readonly initialTab?: typeof MAIN_TAB_DIRECTORY | typeof MAIN_TAB_ACTIVE;
}

export function IpConnectionsPage({
  initialTab = MAIN_TAB_DIRECTORY,
}: IpConnectionsPageProps = {}) {
  const { navigation, tenantId, baseUrl } = useIpWorkspace();
  const [mainTab, setMainTab] = useState<string>(initialTab);
  const [activeSearch, setActiveSearch] = useState('');
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [configuredApp, setConfiguredApp] = useState<CatalogAppSummary | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [connectionToDelete, setConnectionToDelete] = useState<Connection | null>(null);
  const deleteMutation = useDeleteConnectionMutation();

  // 1. Fetch catalog apps for the plugin directory and active connection metadata lookup
  const allCatalogView = useCatalogAppsQuery();
  const catalogView = useCatalogAppsQuery({
    category: selectedCategory || undefined,
    search: search.trim() || undefined,
  });
  const apps = catalogView.data ?? [];
  const catalogAppsById = useMemo(() => {
    const map = new Map<string, CatalogAppSummary>();
    for (const app of allCatalogView.data ?? apps) {
      map.set(app.appId, app);
    }
    return map;
  }, [allCatalogView.data, apps]);

  const categoryPills = useMemo(
    () => deriveCategoryPills(allCatalogView.data ?? apps),
    [allCatalogView.data, apps],
  );

  // 2. Fetch all connections for badge count and Active Apps card grid
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
              {categoryPills.map((cat) => {
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
                          {getAppIcon(app.category, app.runtimeArchitecture)}
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
        <div className="space-y-5">
          <ApiProblemBanner
            problem={allConnectionsView.problem}
            onRetry={() => void allConnectionsView.refetch()}
          />

          {/* Search and Count Toolbar */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative w-full max-w-md">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={activeSearch}
                onChange={(e) => setActiveSearch(e.target.value)}
                placeholder="Search active apps by name, connector, or status..."
                className="pl-9"
              />
            </div>
            <span className="text-xs text-muted-foreground tabular-nums">
              {filteredConnections.length} configured
            </span>
          </div>

          {allConnectionsView.isLoading ? (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-48 w-full rounded-2xl" />
              ))}
            </div>
          ) : filteredConnections.length === 0 ? (
            <div className="flex min-h-[240px] flex-col items-center justify-center rounded-2xl border border-dashed border-border p-8 text-center">
              <Cable className="h-8 w-8 text-muted-foreground" />
              <h3 className="mt-3 font-semibold text-foreground">No Active Apps</h3>
              <p className="mt-1 max-w-sm text-xs text-muted-foreground">
                No active connections matched your search. Explore All Apps to connect your first
                integration.
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setMainTab(MAIN_TAB_DIRECTORY)}
                className="mt-4"
              >
                Browse All Apps
              </Button>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {filteredConnections.map((conn) => {
                const catalogApp = catalogAppsById.get(conn.appId);
                return (
                  <ActiveConnectionCard
                    key={conn.id}
                    connection={conn}
                    catalogApp={catalogApp}
                    appIcon={getAppIcon(catalogApp?.category, catalogApp?.runtimeArchitecture)}
                    baseUrl={baseUrl}
                    tenantId={tenantId}
                    onOpenDetail={(id) => navigation.toConnectionDetail(id)}
                    onRequestDelete={(c) => setConnectionToDelete(c)}
                  />
                );
              })}
            </div>
          )}
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
