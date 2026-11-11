import { ApiErrorCode, type ApiProblem, err, ok, type Result } from '@soopa/ui';
import type { AppSpec, CatalogAppSummary, CatalogAppsFilter } from '../domain/catalog';
import type {
  CheckConnectionInput,
  Connection,
  ConnectionCheckResult,
  CreateConnectionInput,
  DiscoveredCatalog,
  RelinkConnectionInput,
  SimulatePushInput,
  SimulatePushResult,
  UpdateConnectionInput,
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
  UNIVERSAL_SIMULATOR_APP_ID,
} from '../domain/enums';
import type {
  BatchManifestSummary,
  BatchReconciliationOverview,
  DailyTouRollup,
  IntervalLineageTrace,
  IntervalWindowCompleteness,
} from '../domain/intervals';
import {
  type CreateSimulatorEntityInput,
  SIMULATOR_STREAM_LIMITS,
  type SimulatorEntity,
  SimulatorVelocityMode,
  type UpdateSimulatorEntityInput,
} from '../domain/simulator';
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
  GlobalEntityMapEntry,
  InboundRecord,
  IpTrace,
  IpTraceLineageItem,
  ListRecentTracesFilter,
  NormalizedRecord,
  ReplayTransactionResult,
  ReplicaRecord,
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
import type {
  GetCompletenessParams,
  GetDailyTouRollupsParams,
  GetReconciliationParams,
  IntervalRepositoryPort,
} from '../ports/interval-repository.port';
import type {
  ListGemRecordsFilter,
  ListInboundRecordsFilter,
  ListNormalizedRecordsFilter,
  ListReplicaRecordsFilter,
  RecordRepositoryPort,
} from '../ports/record-repository.port';
import type { SimulatorRepositoryPort } from '../ports/simulator-repository.port';
import type { StitchRepositoryPort } from '../ports/stitch-repository.port';
import type { SyncRunRepositoryPort } from '../ports/sync-run-repository.port';
import type { TraceRepositoryPort } from '../ports/trace-repository.port';
import type { TransformationRepositoryPort } from '../ports/transformation-repository.port';
import type { IpNavigationPort, IpRepositoriesBundle } from '../provider/IpRepositoriesContext';
import {
  SEED_CATALOG_APPS,
  SEED_CONNECTION,
  SEED_DAILY_TOU_ROLLUPS,
  SEED_DISCOVERED_CATALOG,
  SEED_INTERVAL_COMPLETENESS,
  SEED_INTERVAL_LINEAGE_TRACE,
  SEED_RECONCILIATION_OVERVIEW,
  SEED_SIMULATOR_APP_SPEC,
  SEED_SIMULATOR_ENTITY,
  SEED_SOURCE_APP_SPEC,
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

function conflictProblem(message: string): ApiProblem {
  return {
    code: ApiErrorCode.CONFLICT,
    status: 409,
    message,
  };
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export class InMemorySimulatorRepository implements SimulatorRepositoryPort {
  public readonly entities: SimulatorEntity[];
  private nextEntityIndex = 1;

  constructor(entities: readonly SimulatorEntity[] = [SEED_SIMULATOR_ENTITY]) {
    this.entities = [...entities];
  }

  public async listEntities(
    tenantId: string,
    connectionId: string,
  ): Promise<Result<readonly SimulatorEntity[], ApiProblem>> {
    return ok(
      this.entities.filter((e) => e.tenantId === tenantId && e.connectionId === connectionId),
    );
  }

  public async createEntity(
    tenantId: string,
    connectionId: string,
    input: CreateSimulatorEntityInput,
  ): Promise<Result<SimulatorEntity, ApiProblem>> {
    const cleanName = input.entityName.trim();
    if (
      this.entities.some(
        (e) =>
          e.tenantId === tenantId &&
          e.connectionId === connectionId &&
          e.entityName.toLowerCase() === cleanName.toLowerCase(),
      )
    ) {
      return err(
        conflictProblem(`Entity "${cleanName}" already exists in connection ${connectionId}.`),
      );
    }
    const idx = this.nextEntityIndex++;
    const candidate =
      Array.isArray(input.sampleBlueprint) && input.sampleBlueprint.length > 0
        ? input.sampleBlueprint[0]
        : input.sampleBlueprint;
    const sampleObj: Record<string, unknown> = isPlainObject(candidate) ? candidate : {};
    const inferredProps: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(sampleObj)) {
      inferredProps[k] = { type: typeof v === 'number' ? 'number' : 'string' };
    }
    const entity: SimulatorEntity = {
      id: `sim_ent_${String(idx).padStart(24, '0')}`,
      tenantId,
      connectionId,
      entityName: cleanName,
      primaryKeyField: input.primaryKeyField?.trim() || 'id',
      cursorField: input.cursorField?.trim() || SIMULATOR_STREAM_LIMITS.DEFAULT_CURSOR_FIELD,
      recordsPerPull: input.recordsPerPull ?? SIMULATOR_STREAM_LIMITS.DEFAULT_RECORDS_PER_PULL,
      cursorStepSeconds:
        input.cursorStepSeconds ?? SIMULATOR_STREAM_LIMITS.DEFAULT_CURSOR_STEP_SECONDS,
      velocityMode: input.velocityMode ?? SimulatorVelocityMode.ENTITY_TRANSACTIONAL,
      sampleBlueprint: input.sampleBlueprint,
      inferredJsonSchema: {
        type: 'object',
        properties: inferredProps,
      },
      chaosPolicy: input.chaosPolicy ?? {},
      version: 1,
      createdAt: '2026-11-11T10:05:00Z',
      updatedAt: '2026-11-11T10:05:00Z',
    };
    this.entities.push(entity);
    return ok(entity);
  }

  public async updateEntity(
    tenantId: string,
    connectionId: string,
    entityId: string,
    input: UpdateSimulatorEntityInput,
  ): Promise<Result<SimulatorEntity, ApiProblem>> {
    const idx = this.entities.findIndex(
      (e) => e.tenantId === tenantId && e.connectionId === connectionId && e.id === entityId,
    );
    const existing = this.entities[idx];
    if (idx < 0 || !existing) {
      return err(notFoundProblem(`Entity ${entityId} not found`));
    }
    const nextName = input.entityName?.trim() || existing.entityName;
    if (
      nextName !== existing.entityName &&
      this.entities.some(
        (e) =>
          e.tenantId === tenantId &&
          e.connectionId === connectionId &&
          e.entityName.toLowerCase() === nextName.toLowerCase(),
      )
    ) {
      return err(
        conflictProblem(`Entity "${nextName}" already exists in connection ${connectionId}.`),
      );
    }
    const updated: SimulatorEntity = {
      ...existing,
      entityName: nextName,
      sampleBlueprint: input.sampleBlueprint ?? existing.sampleBlueprint,
      primaryKeyField: input.primaryKeyField?.trim() || existing.primaryKeyField,
      cursorField: input.cursorField?.trim() || existing.cursorField,
      recordsPerPull: input.recordsPerPull ?? existing.recordsPerPull,
      cursorStepSeconds: input.cursorStepSeconds ?? existing.cursorStepSeconds,
      velocityMode: input.velocityMode ?? existing.velocityMode,
      chaosPolicy: input.chaosPolicy ?? existing.chaosPolicy,
      version: existing.version + 1,
      updatedAt: '2026-11-11T10:10:00Z',
    };
    this.entities[idx] = updated;
    return ok(updated);
  }

  public async deleteEntity(
    tenantId: string,
    connectionId: string,
    entityId: string,
  ): Promise<Result<void, ApiProblem>> {
    const idx = this.entities.findIndex(
      (e) => e.tenantId === tenantId && e.connectionId === connectionId && e.id === entityId,
    );
    if (idx < 0) {
      return err(notFoundProblem(`Entity ${entityId} not found`));
    }
    this.entities.splice(idx, 1);
    return ok(undefined);
  }
}

export class InMemoryCatalogRepository implements CatalogRepositoryPort {
  private readonly apps: CatalogAppSummary[];
  private readonly specs: Map<string, AppSpec>;

  constructor(
    apps: readonly CatalogAppSummary[] = SEED_CATALOG_APPS,
    specs: readonly AppSpec[] = [SEED_SOURCE_APP_SPEC, SEED_SIMULATOR_APP_SPEC],
  ) {
    this.apps = [...apps];
    this.specs = new Map(specs.map((spec) => [spec.appId, spec]));
  }

  public async listApps(
    _tenantId: string,
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

  public async getAppSpec(_tenantId: string, appId: string): Promise<Result<AppSpec, ApiProblem>> {
    const spec = this.specs.get(appId);
    return spec ? ok(spec) : err(notFoundProblem(`AppSpec ${appId} not found`));
  }
}

export class InMemoryConnectionRepository implements ConnectionRepositoryPort {
  public readonly items: Connection[];
  private readonly catalogs: Map<string, DiscoveredCatalog>;
  private readonly simulator?: InMemorySimulatorRepository;

  constructor(
    initial: readonly Connection[] = [SEED_CONNECTION],
    catalogs: readonly DiscoveredCatalog[] = [SEED_DISCOVERED_CATALOG],
    simulator?: InMemorySimulatorRepository,
  ) {
    this.items = [...initial];
    this.catalogs = new Map(catalogs.map((cat) => [cat.connectionId, cat]));
    this.simulator = simulator;
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
    if (input.appId === UNIVERSAL_SIMULATOR_APP_ID) {
      return ok({
        success: true,
        status: ConnectionHandshakeStatus.VERIFIED,
        message: 'Universal Schema Simulator connection ready.',
        errorCode: null,
      });
    }
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

  private nextConnectionIndex = 1;

  public async createConnection(
    tenantId: string,
    input: CreateConnectionInput,
  ): Promise<Result<Connection, ApiProblem>> {
    const uniqueId = `conn_created_${Date.now()}_${this.nextConnectionIndex++}`;
    const created: Connection = {
      id: uniqueId,
      tenantId,
      appId: input.appId,
      name: input.name,
      authType: input.authType,
      publicConfig: input.publicConfig,
      status: ConnectionStatus.ACTIVE,
      connectionFingerprint: `fp_${input.appId}_${input.endpointForFingerprint ?? uniqueId}`,
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
    tenantId: string,
    connectionId: string,
  ): Promise<Result<DiscoveredCatalog, ApiProblem>> {
    const conn = this.items.find((c) => c.tenantId === tenantId && c.id === connectionId);
    if (!conn) {
      return err(notFoundProblem(`Connection ${connectionId} not found`));
    }
    if (conn.appId === UNIVERSAL_SIMULATOR_APP_ID && this.simulator) {
      const entitiesRes = await this.simulator.listEntities(tenantId, connectionId);
      if (!entitiesRes.ok) {
        return err(entitiesRes.error);
      }
      const discovered: DiscoveredCatalog = {
        connectionId,
        catalogVersion: (this.catalogs.get(connectionId)?.catalogVersion ?? 0) + 1,
        catalogHash: `hash_sim_${connectionId}_${entitiesRes.value.length}`,
        discoveredAt: '2026-11-11T10:15:00Z',
        streams: entitiesRes.value.map((ent) => {
          const schemaProps = isPlainObject(ent.inferredJsonSchema.properties)
            ? ent.inferredJsonSchema.properties
            : {};
          return {
            name: ent.entityName,
            primaryKey: [ent.primaryKeyField],
            cursorField: ent.cursorField,
            supportedSyncModes: [SyncRunKind.INCREMENTAL, SyncRunKind.FULL_REFRESH],
            fields: Object.keys(schemaProps).map((fieldName) => ({
              name: fieldName,
              dataType: 'string',
              nullable: fieldName !== ent.primaryKeyField,
              description: null,
            })),
          };
        }),
      };
      this.catalogs.set(connectionId, discovered);
      return ok(discovered);
    }
    const catalog = this.catalogs.get(connectionId);
    if (catalog) {
      return ok(catalog);
    }
    const sampleNames =
      conn.appId === 'stripe'
        ? ['customers', 'invoices', 'charges']
        : conn.appId === 'salesforce'
          ? ['contacts', 'accounts', 'opportunities']
          : conn.appId === 'hubspot'
            ? ['contacts', 'companies', 'deals']
            : ['posts', 'users', 'comments'];
    const generated: DiscoveredCatalog = {
      connectionId,
      catalogVersion: 1,
      catalogHash: `hash_${connectionId}`,
      discoveredAt: '2026-11-05T12:00:00Z',
      streams: sampleNames.map((name) => ({
        name,
        primaryKey: ['id'],
        cursorField: 'updated_at',
        supportedSyncModes: [SyncRunKind.INCREMENTAL, SyncRunKind.FULL_REFRESH],
        fields: [{ name: 'id', dataType: 'string', nullable: false, description: 'Identifier' }],
      })),
    };
    this.catalogs.set(connectionId, generated);
    return ok(generated);
  }

  public async updateConnection(
    tenantId: string,
    connectionId: string,
    input: UpdateConnectionInput,
  ): Promise<Result<Connection, ApiProblem>> {
    const idx = this.items.findIndex((c) => c.tenantId === tenantId && c.id === connectionId);
    const existing = this.items[idx];
    if (idx < 0 || !existing) {
      return err(notFoundProblem(`Connection ${connectionId} not found`));
    }
    const updated: Connection = {
      ...existing,
      name: input.newName ?? existing.name,
      publicConfig: input.updatedPublicConfig
        ? { ...existing.publicConfig, ...input.updatedPublicConfig }
        : existing.publicConfig,
      updatedAt: '2026-10-29T09:10:00Z',
    };
    this.items[idx] = updated;
    return ok(updated);
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
      publicConfig: input.updatedPublicConfig
        ? { ...existing.publicConfig, ...input.updatedPublicConfig }
        : existing.publicConfig,
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

  public async deleteConnection(
    tenantId: string,
    connectionId: string,
  ): Promise<Result<void, ApiProblem>> {
    const idx = this.items.findIndex((c) => c.tenantId === tenantId && c.id === connectionId);
    if (idx < 0) {
      return err(notFoundProblem(`Connection ${connectionId} not found`));
    }
    this.items.splice(idx, 1);
    return ok(undefined);
  }

  public async simulatePush(
    tenantId: string,
    connectionId: string,
    input: SimulatePushInput,
  ): Promise<Result<SimulatePushResult, ApiProblem>> {
    const existing = this.items.find((c) => c.tenantId === tenantId && c.id === connectionId);
    if (!existing) {
      return err(notFoundProblem(`Connection ${connectionId} not found`));
    }
    const count = Math.max(1, input.count ?? 1);
    return ok({
      connectionId,
      streamName: input.streamName,
      recordsPushed: count,
      recordIds: Array.from({ length: count }, (_, i) => `SIM-${String(i + 1).padStart(6, '0')}`),
      traceIds: Array.from(
        { length: count },
        (_, i) => `trc_sim_${String(i + 1).padStart(3, '0')}`,
      ),
      status: 'ACCEPTED',
    });
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
      input.shadowTransformationVersion ? { unit: { active: 'COUNT', shadow: 'count' } } : {};
    return ok({
      transformationId: input.transformationId,
      transformationVersion: input.transformationVersion,
      drafts: [
        {
          canonicalType: 'canonical.record_alpha.v1',
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

export class InMemoryRecordRepository implements RecordRepositoryPort {
  public normalizedRecords: NormalizedRecord[] = [];
  public gemRecords: GlobalEntityMapEntry[] = [];
  public replicaRecords: ReplicaRecord[] = [];
  public inboundRecords: InboundRecord[] = [];

  public async listNormalizedRecords(
    tenantId: string,
    filter?: ListNormalizedRecordsFilter,
  ): Promise<Result<readonly NormalizedRecord[], ApiProblem>> {
    let res = this.normalizedRecords.filter((r) => r.tenantId === tenantId);
    if (filter?.connectionId) {
      res = res.filter((r) => r.connectionId === filter.connectionId);
    }
    if (filter?.canonicalType) {
      res = res.filter((r) => r.canonicalType === filter.canonicalType);
    }
    const offset = filter?.offset ?? 0;
    const limit = filter?.limit ?? 50;
    return ok(res.slice(offset, offset + limit));
  }

  public async listGemRecords(
    tenantId: string,
    filter?: ListGemRecordsFilter,
  ): Promise<Result<readonly GlobalEntityMapEntry[], ApiProblem>> {
    let res = this.gemRecords.filter((r) => r.tenantId === tenantId);
    if (filter?.sourceConnectionId) {
      res = res.filter((r) => r.sourceConnectionId === filter.sourceConnectionId);
    }
    if (filter?.entityDomain) {
      res = res.filter((r) => r.entityDomain === filter.entityDomain);
    }
    const offset = filter?.offset ?? 0;
    const limit = filter?.limit ?? 50;
    return ok(res.slice(offset, offset + limit));
  }

  public async listReplicaRecords(
    tenantId: string,
    filter?: ListReplicaRecordsFilter,
  ): Promise<Result<readonly ReplicaRecord[], ApiProblem>> {
    let res = this.replicaRecords.filter((r) => r.tenantId === tenantId);
    if (filter?.connectionId) {
      res = res.filter((r) => r.connectionId === filter.connectionId);
    }
    if (filter?.stream) {
      res = res.filter((r) => r.stream === filter.stream);
    }
    const offset = filter?.offset ?? 0;
    const limit = filter?.limit ?? 50;
    return ok(res.slice(offset, offset + limit));
  }

  public async listInboundRecords(
    tenantId: string,
    filter?: ListInboundRecordsFilter,
  ): Promise<Result<readonly InboundRecord[], ApiProblem>> {
    let res = this.inboundRecords.filter((r) => r.tenantId === tenantId);
    if (filter?.connectionId) {
      res = res.filter((r) => r.connectionId === filter.connectionId);
    }
    if (filter?.streamName) {
      res = res.filter((r) => r.streamName === filter.streamName);
    }
    const offset = filter?.offset ?? 0;
    const limit = filter?.limit ?? 50;
    const page = res.slice(offset, offset + limit);
    if (!filter?.hydratePayloads) {
      return ok(page.map((r) => (r.requestS3Key ? { ...r, requestBody: null } : r)));
    }
    return ok(page);
  }
}

export class InMemoryIntervalRepository implements IntervalRepositoryPort {
  public overview: BatchReconciliationOverview;
  public completeness: IntervalWindowCompleteness[];
  public touRollups: DailyTouRollup[];
  public lineageTrace: IntervalLineageTrace;

  constructor(
    overview: BatchReconciliationOverview = SEED_RECONCILIATION_OVERVIEW,
    completeness: readonly IntervalWindowCompleteness[] = SEED_INTERVAL_COMPLETENESS,
    touRollups: readonly DailyTouRollup[] = SEED_DAILY_TOU_ROLLUPS,
    lineageTrace: IntervalLineageTrace = SEED_INTERVAL_LINEAGE_TRACE,
  ) {
    this.overview = overview;
    this.completeness = [...completeness];
    this.touRollups = [...touRollups];
    this.lineageTrace = lineageTrace;
  }

  public async getReconciliationOverview(
    tenantId: string,
    params?: GetReconciliationParams,
  ): Promise<Result<BatchReconciliationOverview, ApiProblem>> {
    if (tenantId !== this.overview.tenantId) {
      return ok({
        tenantId,
        connectionId: params?.connectionId ?? null,
        totalBatches: 0,
        completedBatches: 0,
        inFlightBatches: 0,
        failedBatches: 0,
        rawIngestedTotal: 0,
        duplicatesDroppedTotal: 0,
        validCanonicalTotal: 0,
        quarantinedHeldTotal: 0,
        inFlightReadingsTotal: 0,
        isZeroLossBalanced: true,
        recentBatches: [],
      });
    }

    const matchingBatches = params?.connectionId
      ? this.overview.recentBatches.filter((b) => b.connectionId === params.connectionId)
      : this.overview.recentBatches;

    const rawIngested = matchingBatches.reduce((sum, b) => sum + b.rawIngestedCount, 0);
    const duplicatesDropped = matchingBatches.reduce((sum, b) => sum + b.duplicatesDroppedCount, 0);
    const validCanonical = matchingBatches.reduce((sum, b) => sum + b.validCanonicalCount, 0);
    const quarantinedHeld = matchingBatches.reduce((sum, b) => sum + b.quarantinedHeldCount, 0);
    const totalBatches = matchingBatches.length;
    const completedBatches = matchingBatches.filter((b) => b.status === 'COMPLETED').length;
    const failedBatches = matchingBatches.filter((b) => b.status === 'FAILED').length;
    const inFlightBatches = totalBatches - completedBatches - failedBatches;
    const isZeroLossBalanced = rawIngested === validCanonical + duplicatesDropped + quarantinedHeld;

    return ok({
      tenantId,
      connectionId: params?.connectionId ?? this.overview.connectionId,
      totalBatches,
      completedBatches,
      inFlightBatches,
      failedBatches,
      rawIngestedTotal: rawIngested,
      duplicatesDroppedTotal: duplicatesDropped,
      validCanonicalTotal: validCanonical,
      quarantinedHeldTotal: quarantinedHeld,
      inFlightReadingsTotal: 0,
      isZeroLossBalanced,
      recentBatches: matchingBatches.slice(0, params?.recentLimit ?? 20),
    });
  }

  public async getDailyCompleteness(
    tenantId: string,
    params: GetCompletenessParams,
  ): Promise<Result<readonly IntervalWindowCompleteness[], ApiProblem>> {
    return ok(
      this.completeness.filter(
        (c) =>
          c.tenantId === tenantId &&
          c.connectionId === params.connectionId &&
          c.serviceDate === params.serviceDate &&
          (!params.streamName || c.streamName === params.streamName),
      ),
    );
  }

  public async getDailyTouRollups(
    tenantId: string,
    params: GetDailyTouRollupsParams,
  ): Promise<Result<readonly DailyTouRollup[], ApiProblem>> {
    return ok(
      this.touRollups.filter(
        (r) =>
          r.tenantId === tenantId &&
          r.serviceDate === params.serviceDate &&
          (!params.connectionId || r.connectionId === params.connectionId) &&
          (!params.feederId || r.feederId === params.feederId) &&
          (!params.sourceDeviceId || r.sourceDeviceId === params.sourceDeviceId),
      ),
    );
  }

  public async traceDeviceIntervals(
    tenantId: string,
    sourceDeviceId: string,
    serviceDate: string,
  ): Promise<Result<IntervalLineageTrace, ApiProblem>> {
    if (
      this.lineageTrace.tenantId === tenantId &&
      this.lineageTrace.sourceDeviceId === sourceDeviceId &&
      this.lineageTrace.serviceDate === serviceDate
    ) {
      return ok(this.lineageTrace);
    }
    return err(notFoundProblem(`Interval lineage for ${sourceDeviceId} not found`));
  }

  public async recordSettlementReceipt(
    tenantId: string,
    batchId: string,
    deliveryReceiptId: string,
  ): Promise<Result<BatchManifestSummary, ApiProblem>> {
    if (this.overview.tenantId !== tenantId) {
      return err(notFoundProblem(`Batch ${batchId} not found in tenant ${tenantId}`));
    }
    const existing = this.overview.recentBatches.find((b) => b.batchId === batchId);
    if (!existing) {
      return err(notFoundProblem(`Batch manifest ${batchId} not found`));
    }
    const updated: BatchManifestSummary = {
      ...existing,
      deliveryReceiptId,
    };
    this.overview = {
      ...this.overview,
      recentBatches: this.overview.recentBatches.map((b) => (b.batchId === batchId ? updated : b)),
    };
    this.touRollups = this.touRollups.map((r) =>
      r.latestBatchId === batchId && r.tenantId === tenantId ? { ...r, deliveryReceiptId } : r,
    );
    if (this.lineageTrace.tenantId === tenantId) {
      this.lineageTrace = {
        ...this.lineageTrace,
        intervals: this.lineageTrace.intervals.map((pt) =>
          pt.sourceBatchId === batchId ? { ...pt, deliveryReceiptId } : pt,
        ),
      };
    }
    return ok(updated);
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

  public readonly toIntervals = (connectionId?: string): void => {
    this.visited.push(
      connectionId ? `/tenant/ip/intervals?connectionId=${connectionId}` : '/tenant/ip/intervals',
    );
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
  readonly records: InMemoryRecordRepository;
  readonly intervals: InMemoryIntervalRepository;
  readonly simulator: InMemorySimulatorRepository;
  readonly navigation: InMemoryNavigationFake;
}

export function createInMemoryIpWorkspaceSeed(): InMemoryIpWorkspaceHarness {
  const catalog = new InMemoryCatalogRepository();
  const simulator = new InMemorySimulatorRepository();
  const connections = new InMemoryConnectionRepository(
    [SEED_CONNECTION],
    [SEED_DISCOVERED_CATALOG],
    simulator,
  );
  const syncRuns = new InMemorySyncRunRepository();
  const transformations = new InMemoryTransformationRepository();
  const stitches = new InMemoryStitchRepository();
  const traces = new InMemoryTraceRepository();
  const records = new InMemoryRecordRepository();
  const intervals = new InMemoryIntervalRepository();
  const navigation = new InMemoryNavigationFake();

  return {
    repositories: {
      catalog,
      connections,
      syncRuns,
      transformations,
      stitches,
      traces,
      records,
      intervals,
      simulator,
    },
    catalog,
    connections,
    syncRuns,
    transformations,
    stitches,
    traces,
    records,
    intervals,
    simulator,
    navigation,
  };
}
