import { ApiErrorCode, type ApiProblem, err, ok, type Result } from '@soopa/ui';
import type { AppSpec, CatalogAppSummary, CatalogAppsFilter } from '../domain/catalog';
import type {
  CheckConnectionInput,
  Connection,
  ConnectionCheckResult,
  CreateConnectionInput,
  DiscoveredCatalog,
  RelinkConnectionInput,
} from '../domain/connection';
import {
  ConnectionHandshakeStatus,
  ConnectionStatus,
  type JsonRecord,
  PipelineLayer,
  ReplayDispatchStatus,
  type ReplayStageValue,
  StitchRunStatus,
  SyncRunKind,
  SyncRunStatus,
  TraceStatus,
} from '../domain/enums';
import type {
  ListStitchRunsFilter,
  RegisterStitchInput,
  Stitch,
  StitchDefinition,
  StitchRun,
  TriggerStitchEventInput,
  TriggerStitchEventResult,
} from '../domain/stitch';
import type { StreamState, SyncRun, TriggerSyncRunInput } from '../domain/sync-run';
import type {
  BulkReplayResult,
  IpTrace,
  IpTraceLineageItem,
  ListRecentTracesFilter,
  ReplayTransactionResult,
} from '../domain/trace';
import type {
  BindStreamTransformationInput,
  PreviewStreamTransformationInput,
  PromoteTransformationResult,
  RegisteredTransformer,
  Transformation,
  TransformationPreviewResult,
} from '../domain/transformation';
import type { CatalogRepositoryPort } from '../ports/catalog-repository.port';
import type { ConnectionRepositoryPort } from '../ports/connection-repository.port';
import type { StitchRepositoryPort } from '../ports/stitch-repository.port';
import type { SyncRunRepositoryPort } from '../ports/sync-run-repository.port';
import type { TraceRepositoryPort } from '../ports/trace-repository.port';
import type { TransformationRepositoryPort } from '../ports/transformation-repository.port';
import type { IpNavigationPort, IpRepositoriesBundle } from '../provider/IpRepositoriesContext';
import {
  SEED_CATALOG_APPS,
  SEED_CONNECTION,
  SEED_DISCOVERED_CATALOG,
  SEED_ITRON_APP_SPEC,
  SEED_STITCH,
  SEED_STITCH_DEFINITION,
  SEED_STITCH_RUN,
  SEED_STREAM_STATE,
  SEED_SYNC_RUN,
  SEED_TRACE,
  SEED_TRACE_LINEAGE,
  SEED_TRANSFORMATION,
  SEED_TRANSFORMERS,
} from './seed-fixtures';

function notFoundProblem(message: string): ApiProblem {
  return {
    code: ApiErrorCode.NOT_FOUND,
    status: 404,
    message,
  };
}

export class InMemoryCatalogRepository implements CatalogRepositoryPort {
  private readonly apps: CatalogAppSummary[];
  private readonly specs: Map<string, AppSpec>;

  constructor(
    apps: readonly CatalogAppSummary[] = SEED_CATALOG_APPS,
    specs: readonly AppSpec[] = [SEED_ITRON_APP_SPEC],
  ) {
    this.apps = [...apps];
    this.specs = new Map(specs.map((spec) => [spec.appId, spec]));
  }

  public async listApps(
    filter?: CatalogAppsFilter,
  ): Promise<Result<readonly CatalogAppSummary[], ApiProblem>> {
    const searchLower = filter?.search?.toLowerCase();
    const filtered = this.apps.filter((app) => {
      const categoryOk = !filter?.category || app.category === filter.category;
      const searchOk =
        !searchLower ||
        app.displayName.toLowerCase().includes(searchLower) ||
        app.appId.toLowerCase().includes(searchLower);
      return categoryOk && searchOk;
    });
    return ok(filtered);
  }

  public async getAppSpec(appId: string): Promise<Result<AppSpec, ApiProblem>> {
    const spec = this.specs.get(appId);
    return spec ? ok(spec) : err(notFoundProblem(`AppSpec ${appId} not found`));
  }
}

export class InMemoryConnectionRepository implements ConnectionRepositoryPort {
  public readonly items: Connection[];
  private readonly catalogs: Map<string, DiscoveredCatalog>;

  constructor(
    initial: readonly Connection[] = [SEED_CONNECTION],
    catalogs: readonly DiscoveredCatalog[] = [SEED_DISCOVERED_CATALOG],
  ) {
    this.items = [...initial];
    this.catalogs = new Map(catalogs.map((cat) => [cat.connectionId, cat]));
  }

  public async listConnections(
    tenantId: string,
    status?: string,
  ): Promise<Result<readonly Connection[], ApiProblem>> {
    return ok(
      this.items.filter(
        (conn) => conn.tenantId === tenantId && (!status || conn.status === status),
      ),
    );
  }

  public async getConnection(
    tenantId: string,
    connectionId: string,
  ): Promise<Result<Connection, ApiProblem>> {
    const found = this.items.find((c) => c.tenantId === tenantId && c.id === connectionId);
    return found ? ok(found) : err(notFoundProblem(`Connection ${connectionId} not found`));
  }

  public async checkConnection(
    _tenantId: string,
    input: CheckConnectionInput,
  ): Promise<Result<ConnectionCheckResult, ApiProblem>> {
    const hasSecret = Object.keys(input.rawCredentials).length > 0;
    return ok({
      success: hasSecret,
      status: hasSecret
        ? ConnectionHandshakeStatus.VERIFIED
        : ConnectionHandshakeStatus.AUTH_FAILED,
      message: hasSecret ? 'Handshake verified' : 'Missing credentials',
      errorCode: hasSecret ? null : 'MISSING_SECRET',
    });
  }

  public async createConnection(
    tenantId: string,
    input: CreateConnectionInput,
  ): Promise<Result<Connection, ApiProblem>> {
    const created: Connection = {
      id: `conn_created_${this.items.length + 1}`,
      tenantId,
      appId: input.appId,
      name: input.name,
      authType: input.authType,
      publicConfig: input.publicConfig,
      status: ConnectionStatus.ACTIVE,
      connectionFingerprint: `fp_${input.appId}_${this.items.length + 1}`,
      tokenExpiresAt: null,
      lastRefreshedAt: '2026-10-29T09:00:00Z',
      lastErrorCode: null,
      lastErrorMessage: null,
      createdAt: '2026-10-29T09:00:00Z',
      updatedAt: '2026-10-29T09:00:00Z',
      deactivatedAt: null,
    };
    this.items.push(created);
    return ok(created);
  }

  public async discoverCatalog(
    _tenantId: string,
    connectionId: string,
  ): Promise<Result<DiscoveredCatalog, ApiProblem>> {
    const catalog = this.catalogs.get(connectionId);
    return catalog ? ok(catalog) : err(notFoundProblem(`Catalog for ${connectionId} not found`));
  }

  public async relinkConnection(
    tenantId: string,
    connectionId: string,
    input: RelinkConnectionInput,
  ): Promise<Result<Connection, ApiProblem>> {
    const idx = this.items.findIndex((c) => c.tenantId === tenantId && c.id === connectionId);
    const existing = this.items[idx];
    if (idx < 0 || !existing) {
      return err(notFoundProblem(`Connection ${connectionId} not found`));
    }
    const updated: Connection = {
      ...existing,
      name: input.newName ?? existing.name,
      status: ConnectionStatus.ACTIVE,
      updatedAt: '2026-10-29T09:10:00Z',
    };
    this.items[idx] = updated;
    return ok(updated);
  }

  public async deactivateConnection(
    tenantId: string,
    connectionId: string,
  ): Promise<Result<Connection, ApiProblem>> {
    const idx = this.items.findIndex((c) => c.tenantId === tenantId && c.id === connectionId);
    const existing = this.items[idx];
    if (idx < 0 || !existing) {
      return err(notFoundProblem(`Connection ${connectionId} not found`));
    }
    const updated: Connection = {
      ...existing,
      status: ConnectionStatus.DEACTIVATED,
      deactivatedAt: '2026-10-29T09:15:00Z',
    };
    this.items[idx] = updated;
    return ok(updated);
  }
}

export class InMemorySyncRunRepository implements SyncRunRepositoryPort {
  public readonly runs: SyncRun[];
  public readonly states: StreamState[];

  constructor(
    runs: readonly SyncRun[] = [SEED_SYNC_RUN],
    states: readonly StreamState[] = [SEED_STREAM_STATE],
  ) {
    this.runs = [...runs];
    this.states = [...states];
  }

  public async listSyncRuns(
    tenantId: string,
    connectionId: string,
    limit = 50,
  ): Promise<Result<readonly SyncRun[], ApiProblem>> {
    return ok(
      this.runs
        .filter((r) => r.tenantId === tenantId && r.connectionId === connectionId)
        .slice(0, limit),
    );
  }

  public async getSyncRun(
    tenantId: string,
    connectionId: string,
    runId: string,
  ): Promise<Result<SyncRun, ApiProblem>> {
    const found = this.runs.find(
      (r) => r.tenantId === tenantId && r.connectionId === connectionId && r.runId === runId,
    );
    return found ? ok(found) : err(notFoundProblem(`SyncRun ${runId} not found`));
  }

  public async triggerSyncRun(
    tenantId: string,
    connectionId: string,
    input: TriggerSyncRunInput,
  ): Promise<Result<SyncRun, ApiProblem>> {
    const created: SyncRun = {
      runId: `sync_triggered_${this.runs.length + 1}`,
      tenantId,
      connectionId,
      streamName: input.streamName,
      kind: input.forcedKind ?? SyncRunKind.INCREMENTAL,
      generationId: this.runs.length + 1,
      status: SyncRunStatus.QUEUED,
      startCheckpoint: null,
      endCheckpoint: null,
      pagesCount: 0,
      recordsCount: 0,
      bytesCount: 0,
      retryCount: 0,
      errorCode: null,
      errorMessage: null,
      traceId: `trc_sync_${this.runs.length + 1}`,
      startedAt: null,
      finishedAt: null,
      createdAt: '2026-10-29T09:20:00Z',
    };
    this.runs.unshift(created);
    return ok(created);
  }

  public async listStreamStates(
    tenantId: string,
    connectionId: string,
  ): Promise<Result<readonly StreamState[], ApiProblem>> {
    return ok(
      this.states.filter((s) => s.tenantId === tenantId && s.connectionId === connectionId),
    );
  }

  public async resetStreamCheckpoint(
    tenantId: string,
    connectionId: string,
    streamName: string,
  ): Promise<Result<StreamState, ApiProblem>> {
    const idx = this.states.findIndex(
      (s) =>
        s.tenantId === tenantId && s.connectionId === connectionId && s.streamName === streamName,
    );
    const existing = this.states[idx];
    if (idx < 0 || !existing) {
      return err(notFoundProblem(`StreamState ${streamName} not found`));
    }
    const reset: StreamState = {
      ...existing,
      cursorValue: null,
      recordsSyncedCount: 0,
    };
    this.states[idx] = reset;
    return ok(reset);
  }
}

export class InMemoryTransformationRepository implements TransformationRepositoryPort {
  private readonly transformers: RegisteredTransformer[];
  public readonly bindings: Transformation[];

  constructor(
    transformers: readonly RegisteredTransformer[] = SEED_TRANSFORMERS,
    bindings: readonly Transformation[] = [SEED_TRANSFORMATION],
  ) {
    this.transformers = [...transformers];
    this.bindings = [...bindings];
  }

  public async listRegisteredTransformers(): Promise<
    Result<readonly RegisteredTransformer[], ApiProblem>
  > {
    return ok(this.transformers);
  }

  public async listConnectionTransformations(
    tenantId: string,
    connectionId: string,
  ): Promise<Result<readonly Transformation[], ApiProblem>> {
    return ok(
      this.bindings.filter((b) => b.tenantId === tenantId && b.connectionId === connectionId),
    );
  }

  public async getStreamTransformation(
    tenantId: string,
    connectionId: string,
    stream: string,
  ): Promise<Result<Transformation, ApiProblem>> {
    const found = this.bindings.find(
      (b) => b.tenantId === tenantId && b.connectionId === connectionId && b.stream === stream,
    );
    return found ? ok(found) : err(notFoundProblem(`Transformation for ${stream} not found`));
  }

  public async bindStreamTransformation(
    tenantId: string,
    connectionId: string,
    stream: string,
    input: BindStreamTransformationInput,
  ): Promise<Result<Transformation, ApiProblem>> {
    const idx = this.bindings.findIndex(
      (b) => b.tenantId === tenantId && b.connectionId === connectionId && b.stream === stream,
    );
    const existing = this.bindings[idx];
    const next: Transformation = {
      id: existing?.id ?? `trn_bound_${this.bindings.length + 1}`,
      tenantId,
      connectionId,
      stream,
      transformationId: input.transformationId,
      transformationVersion: input.transformationVersion,
      mode: input.mode,
      shadowTransformationVersion: input.shadowTransformationVersion ?? null,
      wasCreated: !existing,
    };
    if (idx >= 0) {
      this.bindings[idx] = next;
    } else {
      this.bindings.push(next);
    }
    return ok(next);
  }

  public async promoteShadowVersion(
    tenantId: string,
    connectionId: string,
    stream: string,
  ): Promise<Result<PromoteTransformationResult, ApiProblem>> {
    const idx = this.bindings.findIndex(
      (b) => b.tenantId === tenantId && b.connectionId === connectionId && b.stream === stream,
    );
    const existing = this.bindings[idx];
    if (idx < 0 || !existing || existing.shadowTransformationVersion === null) {
      return err(notFoundProblem(`No shadow version bound on ${stream}`));
    }
    const previousVersion = existing.transformationVersion;
    const promotedVersion = existing.shadowTransformationVersion;
    this.bindings[idx] = {
      ...existing,
      transformationVersion: promotedVersion,
      shadowTransformationVersion: null,
    };
    return ok({
      id: existing.id,
      connectionId,
      stream,
      transformationId: existing.transformationId,
      promotedVersion,
      previousVersion,
    });
  }

  public async previewTransformation(
    _tenantId: string,
    input: PreviewStreamTransformationInput,
  ): Promise<Result<TransformationPreviewResult, ApiProblem>> {
    const shadowDiffs: Readonly<Record<string, Readonly<Record<string, unknown>>>> =
      input.shadowTransformationVersion ? { unit: { active: 'KWH', shadow: 'kWh' } } : {};
    return ok({
      transformationId: input.transformationId,
      transformationVersion: input.transformationVersion,
      drafts: [
        {
          canonicalType: 'energy.meter_interval.v1',
          sourceId: input.recordKey,
          fields: input.samplePayload,
          extensions: {},
          references: [],
        },
      ],
      rejections: [],
      shadowTransformationVersion: input.shadowTransformationVersion ?? null,
      shadowDiffs,
    });
  }
}

export class InMemoryStitchRepository implements StitchRepositoryPort {
  private readonly definitions: StitchDefinition[];
  public readonly stitches: Stitch[];
  public readonly runs: StitchRun[];

  constructor(
    definitions: readonly StitchDefinition[] = [SEED_STITCH_DEFINITION],
    stitches: readonly Stitch[] = [SEED_STITCH],
    runs: readonly StitchRun[] = [SEED_STITCH_RUN],
  ) {
    this.definitions = [...definitions];
    this.stitches = [...stitches];
    this.runs = [...runs];
  }

  public async listDefinitions(): Promise<Result<readonly StitchDefinition[], ApiProblem>> {
    return ok(this.definitions);
  }

  public async getDefinition(
    _tenantId: string,
    workflowId: string,
    version?: number,
  ): Promise<Result<StitchDefinition, ApiProblem>> {
    const found = this.definitions.find(
      (d) => d.workflowId === workflowId && (version === undefined || d.version === version),
    );
    return found ? ok(found) : err(notFoundProblem(`StitchDefinition ${workflowId} not found`));
  }

  public async listStitches(tenantId: string): Promise<Result<readonly Stitch[], ApiProblem>> {
    return ok(this.stitches.filter((s) => s.tenantId === tenantId));
  }

  public async registerStitch(
    tenantId: string,
    input: RegisterStitchInput,
  ): Promise<Result<Stitch, ApiProblem>> {
    const created: Stitch = {
      id: input.stitchId ?? `stc_reg_${this.stitches.length + 1}`,
      tenantId,
      workflowId: input.workflowId,
      workflowVersion: input.workflowVersion,
      canonicalEventType: input.canonicalEventType,
      isTrigger: input.isTrigger,
      conditionEventKey: input.conditionEventKey ?? null,
      idempotencyKeyField: input.idempotencyKeyField,
      concurrencyKeyField: input.concurrencyKeyField ?? null,
      resourceHintField: input.resourceHintField ?? null,
      isActive: input.isActive,
    };
    this.stitches.push(created);
    return ok(created);
  }

  public async dispatchEvent(
    tenantId: string,
    input: TriggerStitchEventInput,
  ): Promise<Result<TriggerStitchEventResult, ApiProblem>> {
    const runId = `run_dispatched_${this.runs.length + 1}`;
    this.runs.unshift({
      runId,
      tenantId,
      workflowId: SEED_STITCH_DEFINITION.workflowId,
      workflowVersion: 1,
      status: StitchRunStatus.RUNNING,
      priority: 'NORMAL',
      concurrencyKey: input.correlationId ?? null,
      idempotencyKey: input.eventId ?? `idem_${runId}`,
      traceId: input.traceId ?? `trc_${runId}`,
      correlationId: input.correlationId ?? null,
      failureCode: null,
      failureDetail: null,
      createdAt: '2026-10-29T09:30:00Z',
      startedAt: '2026-10-29T09:30:00Z',
      finishedAt: null,
      steps: [],
    });
    return ok({
      startedRunIds: [runId],
      deduplicatedRunIds: [],
      signalledStepIds: [],
    });
  }

  public async listRuns(
    tenantId: string,
    filter?: ListStitchRunsFilter,
  ): Promise<Result<readonly StitchRun[], ApiProblem>> {
    const limit = filter?.limit ?? 50;
    const matched = this.runs.filter(
      (r) =>
        r.tenantId === tenantId &&
        (!filter?.workflowId || r.workflowId === filter.workflowId) &&
        (!filter?.status || r.status === filter.status),
    );
    return ok(matched.slice(0, limit));
  }

  public async getRun(tenantId: string, runId: string): Promise<Result<StitchRun, ApiProblem>> {
    const found = this.runs.find((r) => r.tenantId === tenantId && r.runId === runId);
    return found ? ok(found) : err(notFoundProblem(`StitchRun ${runId} not found`));
  }
}

export class InMemoryTraceRepository implements TraceRepositoryPort {
  public readonly traces: Map<string, IpTrace>;
  public readonly lineageItems: IpTraceLineageItem[];

  constructor(
    traces: readonly IpTrace[] = [SEED_TRACE],
    lineageItems: readonly IpTraceLineageItem[] = SEED_TRACE_LINEAGE,
  ) {
    this.traces = new Map(traces.map((t) => [t.traceId, t]));
    this.lineageItems = [...lineageItems];
  }

  public async listRecentTraces(
    _tenantId: string,
    filter?: ListRecentTracesFilter,
  ): Promise<Result<readonly IpTraceLineageItem[], ApiProblem>> {
    const limit = filter?.limit ?? 50;
    const filtered = this.lineageItems.filter(
      (item) =>
        (!filter?.status || item.status === filter.status) &&
        (filter?.minReplayCount === undefined || item.replayCount >= filter.minReplayCount),
    );
    return ok(filtered.slice(0, limit));
  }

  public async searchByCorrelation(
    _tenantId: string,
    correlationId: string,
    limit = 50,
  ): Promise<Result<readonly IpTraceLineageItem[], ApiProblem>> {
    return ok(
      this.lineageItems.filter((item) => item.correlationId === correlationId).slice(0, limit),
    );
  }

  public async getTrace(tenantId: string, traceId: string): Promise<Result<IpTrace, ApiProblem>> {
    const found = this.traces.get(traceId);
    return found && found.tenantId === tenantId
      ? ok(found)
      : err(notFoundProblem(`Trace ${traceId} not found`));
  }

  public async getTraceLineage(
    _tenantId: string,
    traceId: string,
  ): Promise<Result<readonly IpTraceLineageItem[], ApiProblem>> {
    return ok(
      this.lineageItems.filter(
        (item) => item.traceId === traceId || item.originalTraceId === traceId,
      ),
    );
  }

  public async replayTransaction(
    tenantId: string,
    traceId: string,
    stage: ReplayStageValue,
  ): Promise<Result<ReplayTransactionResult, ApiProblem>> {
    const existing = this.traces.get(traceId);
    if (!existing || existing.tenantId !== tenantId) {
      return err(notFoundProblem(`Trace ${traceId} not found`));
    }
    const newTraceId = `trc_replay_${this.lineageItems.length + 1}`;
    const replayCount = existing.replayCount + 1;
    const originalTraceId = existing.originalTraceId;
    this.lineageItems.push({
      traceId: newTraceId,
      correlationId: existing.correlationId,
      status: TraceStatus.INGESTED,
      primaryLayer: PipelineLayer.L5_DELIVER,
      createdAt: '2026-10-29T09:40:00Z',
      replayCount,
      parentTraceId: traceId,
      originalTraceId,
    });
    return ok({
      status: ReplayDispatchStatus.QUEUED,
      originalTraceId,
      parentTraceId: traceId,
      newTraceId,
      stage,
      replayCount,
      correlationId: existing.correlationId,
    });
  }

  public async modifyAndReplayTransaction(
    tenantId: string,
    traceId: string,
    stage: ReplayStageValue,
    _modifiedPayload: JsonRecord,
  ): Promise<Result<ReplayTransactionResult, ApiProblem>> {
    return this.replayTransaction(tenantId, traceId, stage);
  }

  public async bulkReplayTransactions(
    tenantId: string,
    traceIds: readonly string[],
    stage: ReplayStageValue,
  ): Promise<Result<BulkReplayResult, ApiProblem>> {
    const newTraceIds: string[] = [];
    for (const id of traceIds) {
      const res = await this.replayTransaction(tenantId, id, stage);
      if (res.ok) {
        newTraceIds.push(res.value.newTraceId);
      }
    }
    return ok({
      status: ReplayDispatchStatus.COMPLETED,
      stage,
      replayedCount: newTraceIds.length,
      succeededTraceIds: [...traceIds],
      newTraceIds,
      failedItems: [],
    });
  }
}

export class InMemoryNavigationFake implements IpNavigationPort {
  public readonly visited: string[] = [];

  public readonly toCommandCenter = (): void => {
    this.visited.push('/tenant/ip');
  };

  public readonly toTraces = (correlationQuery?: string): void => {
    this.visited.push(
      correlationQuery ? `/tenant/ip/traces?q=${correlationQuery}` : '/tenant/ip/traces',
    );
  };

  public readonly toTraceDetail = (traceId: string): void => {
    this.visited.push(`/tenant/ip/traces/${traceId}`);
  };

  public readonly toConnections = (): void => {
    this.visited.push('/tenant/ip/connections');
  };

  public readonly toConnectionDetail = (connectionId: string): void => {
    this.visited.push(`/tenant/ip/connections/${connectionId}`);
  };

  public readonly toTransformations = (connectionId?: string): void => {
    this.visited.push(
      connectionId
        ? `/tenant/ip/transformations?connectionId=${connectionId}`
        : '/tenant/ip/transformations',
    );
  };

  public readonly toStitches = (): void => {
    this.visited.push('/tenant/ip/stitches');
  };

  public readonly toStitchDefinition = (workflowId: string): void => {
    this.visited.push(`/tenant/ip/stitches/definitions/${workflowId}`);
  };

  public readonly toStitchRun = (runId: string): void => {
    this.visited.push(`/tenant/ip/stitches/runs/${runId}`);
  };
}

export interface InMemoryIpWorkspaceHarness {
  readonly repositories: IpRepositoriesBundle;
  readonly catalog: InMemoryCatalogRepository;
  readonly connections: InMemoryConnectionRepository;
  readonly syncRuns: InMemorySyncRunRepository;
  readonly transformations: InMemoryTransformationRepository;
  readonly stitches: InMemoryStitchRepository;
  readonly traces: InMemoryTraceRepository;
  readonly navigation: InMemoryNavigationFake;
}

export function createInMemoryIpWorkspaceSeed(): InMemoryIpWorkspaceHarness {
  const catalog = new InMemoryCatalogRepository();
  const connections = new InMemoryConnectionRepository();
  const syncRuns = new InMemorySyncRunRepository();
  const transformations = new InMemoryTransformationRepository();
  const stitches = new InMemoryStitchRepository();
  const traces = new InMemoryTraceRepository();
  const navigation = new InMemoryNavigationFake();

  return {
    repositories: {
      catalog,
      connections,
      syncRuns,
      transformations,
      stitches,
      traces,
    },
    catalog,
    connections,
    syncRuns,
    transformations,
    stitches,
    traces,
    navigation,
  };
}
