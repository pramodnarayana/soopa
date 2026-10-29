import type { CatalogAppsFilter } from '../domain/catalog';
import type { ListStitchRunsFilter } from '../domain/stitch';
import type { ListRecentTracesFilter } from '../domain/trace';

export const ipQueryKeys = {
  all: ['ip'] as const,
  catalog: {
    all: () => ['ip', 'catalog'] as const,
    apps: (filter?: CatalogAppsFilter) =>
      ['ip', 'catalog', 'apps', filter?.category ?? '', filter?.search ?? ''] as const,
    spec: (appId: string) => ['ip', 'catalog', 'spec', appId] as const,
  },
  tenant: (tenantId: string) => ['ip', 'tenant', tenantId] as const,
  connections: {
    all: (tenantId: string) => ['ip', 'tenant', tenantId, 'connections'] as const,
    list: (tenantId: string, status?: string) =>
      ['ip', 'tenant', tenantId, 'connections', 'list', status ?? 'ALL'] as const,
    detail: (tenantId: string, connectionId: string) =>
      ['ip', 'tenant', tenantId, 'connections', 'detail', connectionId] as const,
    catalog: (tenantId: string, connectionId: string) =>
      ['ip', 'tenant', tenantId, 'connections', 'catalog', connectionId] as const,
  },
  syncRuns: {
    all: (tenantId: string, connectionId: string) =>
      ['ip', 'tenant', tenantId, 'connections', connectionId, 'sync-runs'] as const,
    list: (tenantId: string, connectionId: string, limit: number) =>
      ['ip', 'tenant', tenantId, 'connections', connectionId, 'sync-runs', limit] as const,
    detail: (tenantId: string, connectionId: string, runId: string) =>
      [
        'ip',
        'tenant',
        tenantId,
        'connections',
        connectionId,
        'sync-runs',
        'detail',
        runId,
      ] as const,
    streamStates: (tenantId: string, connectionId: string) =>
      ['ip', 'tenant', tenantId, 'connections', connectionId, 'stream-states'] as const,
  },
  transformations: {
    transformers: (tenantId: string) =>
      ['ip', 'tenant', tenantId, 'transformations', 'transformers'] as const,
    byConnection: (tenantId: string, connectionId: string) =>
      ['ip', 'tenant', tenantId, 'transformations', 'connection', connectionId] as const,
    byStream: (tenantId: string, connectionId: string, stream: string) =>
      ['ip', 'tenant', tenantId, 'transformations', 'connection', connectionId, stream] as const,
  },
  stitches: {
    definitions: (tenantId: string) =>
      ['ip', 'tenant', tenantId, 'stitches', 'definitions'] as const,
    definition: (tenantId: string, workflowId: string, version?: number) =>
      [
        'ip',
        'tenant',
        tenantId,
        'stitches',
        'definition',
        workflowId,
        version ?? 'latest',
      ] as const,
    list: (tenantId: string) => ['ip', 'tenant', tenantId, 'stitches', 'list'] as const,
    runs: (tenantId: string, filter?: ListStitchRunsFilter) =>
      [
        'ip',
        'tenant',
        tenantId,
        'stitches',
        'runs',
        filter?.workflowId ?? 'ALL',
        filter?.status ?? 'ALL',
        filter?.limit ?? 50,
      ] as const,
    run: (tenantId: string, runId: string) =>
      ['ip', 'tenant', tenantId, 'stitches', 'run', runId] as const,
  },
  traces: {
    all: (tenantId: string) => ['ip', 'tenant', tenantId, 'traces'] as const,
    recent: (tenantId: string, filter?: ListRecentTracesFilter) =>
      [
        'ip',
        'tenant',
        tenantId,
        'traces',
        'recent',
        filter?.status ?? 'ALL',
        filter?.minReplayCount ?? 0,
        filter?.limit ?? 50,
      ] as const,
    search: (tenantId: string, correlationId: string, limit: number) =>
      ['ip', 'tenant', tenantId, 'traces', 'search', correlationId, limit] as const,
    detail: (tenantId: string, traceId: string, hydratePayloads: boolean) =>
      ['ip', 'tenant', tenantId, 'traces', 'detail', traceId, hydratePayloads] as const,
    lineage: (tenantId: string, traceId: string) =>
      ['ip', 'tenant', tenantId, 'traces', 'lineage', traceId] as const,
  },
} as const;
