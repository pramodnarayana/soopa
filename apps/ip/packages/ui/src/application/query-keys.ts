import type { CatalogAppsFilter } from '../domain/catalog';
import type { ListStitchRunsFilter } from '../domain/stitch';
import type { ListRecentTracesFilter } from '../domain/trace';
import type {
  GetCompletenessParams,
  GetDailyTouRollupsParams,
  GetReconciliationParams,
} from '../ports/interval-repository.port';
import type {
  ListGemRecordsFilter,
  ListInboundRecordsFilter,
  ListNormalizedRecordsFilter,
  ListReplicaRecordsFilter,
} from '../ports/record-repository.port';

export const ipQueryKeys = {
  all: ['ip'] as const,
  catalog: {
    all: (tenantId: string) => ['ip', 'tenant', tenantId, 'catalog'] as const,
    apps: (tenantId: string, filter?: CatalogAppsFilter) =>
      [
        'ip',
        'tenant',
        tenantId,
        'catalog',
        'apps',
        filter?.category ?? '',
        filter?.search ?? '',
      ] as const,
    spec: (tenantId: string, appId: string) =>
      ['ip', 'tenant', tenantId, 'catalog', 'spec', appId] as const,
  },
  tenant: (tenantId: string) => ['ip', 'tenant', tenantId] as const,
  connections: {
    all: (tenantId: string) => ['ip', 'tenant', tenantId, 'connections'] as const,
    list: (tenantId: string, status?: string) =>
      ['ip', 'tenant', tenantId, 'connections', 'list', status ?? 'ALL'] as const,
    detail: (tenantId: string, connectionId: string) =>
      ['ip', 'tenant', tenantId, 'connections', 'detail', connectionId] as const,
    discoveredStreams: (tenantId: string, connectionId: string) =>
      ['ip', 'tenant', tenantId, 'connections', connectionId, 'discovered-streams'] as const,
    entities: (tenantId: string, connectionId: string) =>
      ['ip', 'tenant', tenantId, 'connections', connectionId, 'entities'] as const,
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
  records: {
    all: (tenantId: string) => ['ip', 'tenant', tenantId, 'records'] as const,
    normalized: (tenantId: string, filter?: ListNormalizedRecordsFilter) =>
      [
        'ip',
        'tenant',
        tenantId,
        'records',
        'normalized',
        filter?.connectionId ?? '__ALL__',
        filter?.canonicalType ?? '__ALL__',
        filter?.limit ?? 50,
        filter?.offset ?? 0,
      ] as const,
    gem: (tenantId: string, filter?: ListGemRecordsFilter) =>
      [
        'ip',
        'tenant',
        tenantId,
        'records',
        'gem',
        filter?.sourceConnectionId ?? '__ALL__',
        filter?.entityDomain ?? '__ALL__',
        filter?.limit ?? 50,
        filter?.offset ?? 0,
      ] as const,
    replica: (tenantId: string, filter?: ListReplicaRecordsFilter) =>
      [
        'ip',
        'tenant',
        tenantId,
        'records',
        'replica',
        filter?.connectionId ?? '__ALL__',
        filter?.stream ?? '__ALL__',
        filter?.limit ?? 50,
        filter?.offset ?? 0,
      ] as const,
    inbound: (tenantId: string, filter?: ListInboundRecordsFilter) =>
      [
        'ip',
        'tenant',
        tenantId,
        'records',
        'inbound',
        filter?.connectionId ?? '__ALL__',
        filter?.streamName ?? '__ALL__',
        filter?.hydratePayloads ?? false,
        filter?.limit ?? 50,
        filter?.offset ?? 0,
      ] as const,
  },
  intervals: {
    all: (tenantId: string) => ['ip', 'tenant', tenantId, 'intervals'] as const,
    reconciliation: (tenantId: string, params?: GetReconciliationParams) =>
      [
        'ip',
        'tenant',
        tenantId,
        'intervals',
        'reconciliation',
        params?.connectionId ?? '__ALL__',
        params?.recentLimit ?? 20,
      ] as const,
    completeness: (tenantId: string, params: GetCompletenessParams) =>
      [
        'ip',
        'tenant',
        tenantId,
        'intervals',
        'completeness',
        params.connectionId,
        params.serviceDate,
        params.streamName ?? '__ALL__',
      ] as const,
    touRollups: (tenantId: string, params: GetDailyTouRollupsParams) =>
      [
        'ip',
        'tenant',
        tenantId,
        'intervals',
        'tou-rollups',
        params.serviceDate,
        params.feederId ?? '__ALL__',
        params.sourceDeviceId ?? '__ALL__',
      ] as const,
    deviceLineage: (tenantId: string, sourceDeviceId: string, serviceDate: string) =>
      [
        'ip',
        'tenant',
        tenantId,
        'intervals',
        'device-lineage',
        sourceDeviceId,
        serviceDate,
      ] as const,
  },
  simulator: {
    all: (tenantId: string) => ['ip', 'tenant', tenantId, 'simulator'] as const,
    entities: (tenantId: string, connectionId: string) =>
      ['ip', 'tenant', tenantId, 'connections', connectionId, 'simulator-entities'] as const,
  },
} as const;
