import {
  ApiErrorCode,
  type ApiProblem,
  FetchHttpClientAdapter,
  LogLevel,
  type Result,
} from '@soopa/ui';
import { RecordingLoggerFake } from '@soopa/ui/testing';
import { describe, expect, it } from 'vitest';
import {
  HttpCatalogRepository,
  HttpConnectionRepository,
  HttpStitchRepository,
  HttpSyncRunRepository,
  HttpTraceRepository,
  HttpTransformationRepository,
} from '../adapters/http';
import { AuthType, ReplayStage, SyncRunKind, TransformationMode } from '../domain/enums';

function expectOk<T>(result: Result<T, ApiProblem>): T {
  expect(result.ok).toBe(true);
  if (!result.ok) {
    throw new Error(`Expected Ok result, received ${result.error.code}: ${result.error.message}`);
  }
  return result.value;
}

interface RecordedCall {
  readonly method: string;
  readonly url: string;
  readonly bodyText: string | null;
}

function resolveRequestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

function createRouteFetch(routes: Readonly<Record<string, unknown>>): {
  readonly fetchImpl: typeof fetch;
  readonly calls: RecordedCall[];
} {
  const calls: RecordedCall[] = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    const method = init?.method ?? 'GET';
    const url = resolveRequestUrl(input);
    const parsedUrl = new URL(url);
    const key = `${method} ${parsedUrl.pathname}`;
    const bodyText = typeof init?.body === 'string' ? init.body : null;
    calls.push({ method, url, bodyText });
    const payload = routes[key];
    if (payload === undefined) {
      return new Response(JSON.stringify({ detail: `Unmapped ${key}` }), { status: 404 });
    }
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  return { fetchImpl, calls };
}

const WIRE_CONNECTION = {
  id: 'conn_01',
  tenant_id: 'ten_01',
  app_id: 'itron_ami',
  name: 'Itron Prod',
  auth_type: 'OAUTH2',
  public_config: { base_url: 'https://ami.example.com' },
  status: 'ACTIVE',
  connection_fingerprint: 'fp_01',
  created_at: '2026-10-29T08:00:00Z',
  updated_at: '2026-10-29T08:00:00Z',
};

const WIRE_SYNC_RUN = {
  run_id: 'sync_01',
  tenant_id: 'ten_01',
  connection_id: 'conn_01',
  stream_name: 'meter_reads',
  kind: 'INCREMENTAL',
  generation_id: 2,
  status: 'SUCCEEDED',
  pages_count: 3,
  records_count: 150,
  bytes_count: 12400,
  retry_count: 0,
  trace_id: 'trc_01',
  created_at: '2026-10-29T08:00:00Z',
};

const WIRE_STREAM_STATE = {
  state_id: 'st_01',
  tenant_id: 'ten_01',
  connection_id: 'conn_01',
  stream_name: 'meter_reads',
  cursor_field: 'interval_end',
  cursor_value: '2026-10-29T08:00:00Z',
  records_synced_count: 150,
  last_synced_at: '2026-10-29T08:00:05Z',
};

const WIRE_TRANSFORMATION = {
  id: 'trn_01',
  tenant_id: 'ten_01',
  connection_id: 'conn_01',
  stream: 'meter_reads',
  transformation_id: 'itron.meter_read.to_gem',
  transformation_version: 1,
  mode: 'SHADOW',
  shadow_transformation_version: 2,
  was_created: true,
};

const WIRE_STITCH_DEFINITION = {
  workflow_id: 'energy.ami_to_mdm',
  version: 1,
  default_priority: 'HIGH',
  description: 'AMI to MDM',
  nodes: [
    {
      node_key: 'step_1',
      kind: 'TASK',
      step_type: 'ip.stitch.validate',
      parents: [],
      edge_condition: 'ON_SUCCESS',
      effect_policy: 'PURE',
      queue_name: 'ip-dp',
    },
  ],
};

const WIRE_STITCH_RUN = {
  run_id: 'run_01',
  tenant_id: 'ten_01',
  workflow_id: 'energy.ami_to_mdm',
  workflow_version: 1,
  status: 'SUCCEEDED',
  priority: 'HIGH',
  idempotency_key: 'idem_01',
  trace_id: 'trc_01',
  created_at: '2026-10-29T08:00:00Z',
  steps: [
    {
      step_run_id: 'sr_01',
      node_key: 'step_1',
      status: 'SUCCEEDED',
      retry_count: 0,
      app_retry_count: 0,
      internal_retry_count: 0,
      iteration_count: 1,
      created_at: '2026-10-29T08:00:01Z',
    },
  ],
};

describe('Outbound HTTP Repositories — Full 34-Method Contract & Schema Drift Telemetry', () => {
  it('maps HttpCatalogRepository (listApps, getAppSpec) and HttpConnectionRepository (all 7 methods)', async () => {
    const logger = new RecordingLoggerFake();
    const { fetchImpl, calls } = createRouteFetch({
      'GET /api/v1/ip/catalog/apps': [
        {
          app_id: 'itron_ami',
          display_name: 'Itron AMI',
          category: 'energy',
          auth_type: 'OAUTH2',
        },
      ],
      'GET /api/v1/ip/catalog/apps/itron_ami/spec': {
        app_id: 'itron_ami',
        display_name: 'Itron AMI',
        auth_type: 'OAUTH2',
        category: 'energy',
        properties: [
          {
            name: 'region',
            label: 'Region',
            type: 'DROPDOWN',
            options: [{ label: 'US West', value: 'us-west-2' }],
            oauth_config: {
              auth_url: 'https://auth.example.com/authorize',
              token_url: 'https://auth.example.com/token',
              scopes: ['ami:read'],
            },
          },
          {
            name: 'timeout_seconds',
            label: 'Timeout',
            type: 'NUMBER',
            oauth_config: null,
          },
        ],
      },
      'GET /api/v1/tenants/ten_01/ip/connections': [WIRE_CONNECTION],
      'GET /api/v1/tenants/ten_01/ip/connections/conn_01': WIRE_CONNECTION,
      'POST /api/v1/tenants/ten_01/ip/connections/check': {
        success: true,
        status: 'VERIFIED',
        message: 'OK',
      },
      'POST /api/v1/tenants/ten_01/ip/connections': WIRE_CONNECTION,
      'POST /api/v1/tenants/ten_01/ip/connections/conn_01/discover': {
        connection_id: 'conn_01',
        catalog_version: 2,
        catalog_hash: 'hash_02',
        discovered_at: '2026-10-29T08:02:00Z',
        streams: [
          {
            name: 'meter_reads',
            fields: [{ name: 'meter_id', data_type: 'string', nullable: false }],
            primary_key: ['meter_id'],
            cursor_field: 'updated_at',
            supported_sync_modes: ['INCREMENTAL'],
          },
        ],
      },
      'POST /api/v1/tenants/ten_01/ip/connections/conn_01/relink': WIRE_CONNECTION,
      'DELETE /api/v1/tenants/ten_01/ip/connections/conn_01': {
        ...WIRE_CONNECTION,
        status: 'INACTIVE',
      },
    });

    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local',
      fetchImpl,
      logger,
    });
    const catalogRepo = new HttpCatalogRepository(client, logger);
    const connRepo = new HttpConnectionRepository(client, logger);

    const apps = expectOk(await catalogRepo.listApps({ category: 'energy', search: 'itron' }));
    expect(apps[0]?.appId).toBe('itron_ami');

    const spec = expectOk(await catalogRepo.getAppSpec('itron_ami'));
    expect(spec.properties[0]?.oauthConfig?.scopes).toEqual(['ami:read']);

    const listed = expectOk(await connRepo.listConnections('ten_01', 'ACTIVE'));
    expect(listed[0]?.connectionFingerprint).toBe('fp_01');

    const detail = expectOk(await connRepo.getConnection('ten_01', 'conn_01'));
    expect(detail.id).toBe('conn_01');

    const checked = expectOk(
      await connRepo.checkConnection('ten_01', {
        appId: 'itron_ami',
        authType: AuthType.OAUTH2,
        publicConfig: { base_url: 'https://ami.example.com' },
        rawCredentials: { secret: 'sec_1' },
      }),
    );
    expect(checked.success).toBe(true);

    const created = expectOk(
      await connRepo.createConnection('ten_01', {
        appId: 'itron_ami',
        name: 'Itron Prod',
        authType: AuthType.OAUTH2,
        publicConfig: { base_url: 'https://ami.example.com' },
        rawCredentials: { secret: 'sec_1' },
      }),
    );
    expect(created.name).toBe('Itron Prod');

    const discovered = expectOk(await connRepo.discoverCatalog('ten_01', 'conn_01'));
    expect(discovered.streams[0]?.fields[0]?.dataType).toBe('string');

    const relinked = expectOk(
      await connRepo.relinkConnection('ten_01', 'conn_01', {
        newName: 'Itron Rotated',
      }),
    );
    expect(relinked.id).toBe('conn_01');

    const deactivated = expectOk(await connRepo.deactivateConnection('ten_01', 'conn_01'));
    expect(deactivated.status).toBe('INACTIVE');
    expect(calls).toHaveLength(9);
  });

  it('maps HttpSyncRunRepository (all 5 methods) and HttpTransformationRepository (all 6 methods)', async () => {
    const logger = new RecordingLoggerFake();
    const { fetchImpl, calls } = createRouteFetch({
      'GET /api/v1/tenants/ten_01/ip/connections/conn_01/sync-runs': [WIRE_SYNC_RUN],
      'GET /api/v1/tenants/ten_01/ip/connections/conn_01/sync-runs/sync_01': WIRE_SYNC_RUN,
      'POST /api/v1/tenants/ten_01/ip/connections/conn_01/sync-runs': WIRE_SYNC_RUN,
      'GET /api/v1/tenants/ten_01/ip/connections/conn_01/streams/state': [WIRE_STREAM_STATE],
      'POST /api/v1/tenants/ten_01/ip/connections/conn_01/streams/meter_reads/reset': {
        ...WIRE_STREAM_STATE,
        cursor_value: null,
        records_synced_count: 0,
      },
      'GET /api/v1/tenants/ten_01/ip/transformations/transformers': [
        {
          transformation_id: 'itron.meter_read.to_gem',
          transformation_version: 2,
          target_types: ['energy.meter_interval.v1'],
        },
      ],
      'GET /api/v1/tenants/ten_01/ip/transformations/connections/conn_01': [WIRE_TRANSFORMATION],
      'GET /api/v1/tenants/ten_01/ip/transformations/connections/conn_01/streams/meter_reads':
        WIRE_TRANSFORMATION,
      'PUT /api/v1/tenants/ten_01/ip/transformations/connections/conn_01/streams/meter_reads':
        WIRE_TRANSFORMATION,
      'POST /api/v1/tenants/ten_01/ip/transformations/connections/conn_01/streams/meter_reads/promote':
        {
          id: 'trn_01',
          connection_id: 'conn_01',
          stream: 'meter_reads',
          transformation_id: 'itron.meter_read.to_gem',
          promoted_version: 2,
          previous_version: 1,
        },
      'POST /api/v1/tenants/ten_01/ip/transformations/preview': {
        transformation_id: 'itron.meter_read.to_gem',
        transformation_version: 1,
        drafts: [
          {
            canonical_type: 'energy.meter_interval.v1',
            source_id: 'MTR-01',
            fields: { kwh: 12.5 },
            references: [
              {
                field_name: 'service_point',
                target_canonical_type: 'energy.service_point.v1',
                target_source_id: 'SP-01',
              },
            ],
          },
        ],
        rejections: [{ reason: 'WARN_OPTIONAL', field_path: '$.voltage', detail: 'Missing' }],
        shadow_transformation_version: 2,
        shadow_diffs: { kwh: { active: 12.5, shadow: 12.5 } },
      },
    });

    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local',
      fetchImpl,
      logger,
    });
    const syncRepo = new HttpSyncRunRepository(client, logger);
    const transRepo = new HttpTransformationRepository(client, logger);

    const runs = expectOk(await syncRepo.listSyncRuns('ten_01', 'conn_01'));
    expect(runs[0]?.recordsCount).toBe(150);

    const singleRun = expectOk(await syncRepo.getSyncRun('ten_01', 'conn_01', 'sync_01'));
    expect(singleRun.runId).toBe('sync_01');

    const triggered = expectOk(
      await syncRepo.triggerSyncRun('ten_01', 'conn_01', {
        streamName: 'meter_reads',
        forcedKind: SyncRunKind.FULL_REFRESH,
      }),
    );
    expect(triggered.runId).toBe('sync_01');

    const states = expectOk(await syncRepo.listStreamStates('ten_01', 'conn_01'));
    expect(states[0]?.cursorField).toBe('interval_end');

    const reset = expectOk(
      await syncRepo.resetStreamCheckpoint('ten_01', 'conn_01', 'meter_reads'),
    );
    expect(reset.cursorValue).toBeNull();

    const transformers = expectOk(await transRepo.listRegisteredTransformers('ten_01'));
    expect(transformers[0]?.transformationVersion).toBe(2);

    const connTrans = expectOk(await transRepo.listConnectionTransformations('ten_01', 'conn_01'));
    expect(connTrans[0]?.shadowTransformationVersion).toBe(2);

    const streamTrans = expectOk(
      await transRepo.getStreamTransformation('ten_01', 'conn_01', 'meter_reads'),
    );
    expect(streamTrans.wasCreated).toBe(true);

    const bound = expectOk(
      await transRepo.bindStreamTransformation('ten_01', 'conn_01', 'meter_reads', {
        transformationId: 'itron.meter_read.to_gem',
        transformationVersion: 1,
        mode: TransformationMode.SHADOW,
        shadowTransformationVersion: 2,
      }),
    );
    expect(bound.id).toBe('trn_01');

    const boundActive = expectOk(
      await transRepo.bindStreamTransformation('ten_01', 'conn_01', 'meter_reads', {
        transformationId: 'itron.meter_read.to_gem',
        transformationVersion: 2,
        mode: TransformationMode.ACTIVE,
      }),
    );
    expect(boundActive.id).toBe('trn_01');

    const promoted = expectOk(
      await transRepo.promoteShadowVersion('ten_01', 'conn_01', 'meter_reads'),
    );
    expect(promoted.promotedVersion).toBe(2);

    const preview = expectOk(
      await transRepo.previewTransformation('ten_01', {
        connectionId: 'conn_01',
        stream: 'meter_reads',
        transformationId: 'itron.meter_read.to_gem',
        transformationVersion: 1,
        recordKey: 'MTR-01',
        samplePayload: { kwh: 12.5 },
      }),
    );
    expect(preview.drafts[0]?.references[0]?.targetSourceId).toBe('SP-01');
    expect(calls).toHaveLength(12);
  });

  it('maps HttpStitchRepository (all 7 methods) and HttpTraceRepository (all 7 methods)', async () => {
    const logger = new RecordingLoggerFake();
    const lineageWire = [
      {
        trace_id: 'trc_01',
        correlation_id: 'MTR-77410',
        status: 'FAILED',
        primary_layer: 'L5_DELIVERY',
        created_at: '2026-10-29T08:00:00Z',
        replay_count: 0,
        parent_trace_id: null,
        original_trace_id: 'trc_01',
      },
    ];
    const { fetchImpl, calls } = createRouteFetch({
      'GET /api/v1/tenants/ten_01/ip/stitches/definitions': [WIRE_STITCH_DEFINITION],
      'GET /api/v1/tenants/ten_01/ip/stitches/definitions/energy.ami_to_mdm':
        WIRE_STITCH_DEFINITION,
      'GET /api/v1/tenants/ten_01/ip/stitches': [
        {
          id: 'stc_01',
          tenant_id: 'ten_01',
          workflow_id: 'energy.ami_to_mdm',
          workflow_version: 1,
          canonical_event_type: 'energy.meter_interval.v1',
          is_trigger: true,
          idempotency_key_field: 'source_id',
          is_active: true,
        },
      ],
      'POST /api/v1/tenants/ten_01/ip/stitches': {
        id: 'stc_02',
        tenant_id: 'ten_01',
        workflow_id: 'energy.ami_to_mdm',
        workflow_version: 1,
        canonical_event_type: 'energy.meter_interval.v1',
        is_trigger: true,
        idempotency_key_field: 'source_id',
        is_active: true,
      },
      'POST /api/v1/tenants/ten_01/ip/stitches/dispatch': {
        started_run_ids: ['run_01'],
        deduplicated_run_ids: [],
        signalled_step_ids: [],
      },
      'GET /api/v1/tenants/ten_01/ip/stitches/runs': [WIRE_STITCH_RUN],
      'GET /api/v1/tenants/ten_01/ip/stitches/runs/run_01': WIRE_STITCH_RUN,
      'GET /api/v1/tenants/ten_01/ip/transactions': lineageWire,
      'GET /api/v1/tenants/ten_01/ip/transactions/search': lineageWire,
      'GET /api/v1/tenants/ten_01/ip/transactions/trc_01': {
        trace_id: 'trc_01',
        tenant_id: 'ten_01',
        correlation_id: 'MTR-77410',
        original_trace_id: 'trc_01',
        parent_trace_id: null,
        replay_count: 0,
        status: 'FAILED',
        inbound_record: {
          id: 'inb_01',
          tenant_id: 'ten_01',
          trace_id: 'trc_01',
          connection_id: 'conn_01',
          app_id: 'itron_ami',
          stream_name: 'meter_reads',
          ingestion_mode: 'WEBHOOK',
          request_size_bytes: 64,
          request_sha256: 'sha_01',
          received_at: '2026-10-29T08:00:00Z',
        },
        replica_records: [
          {
            id: 'rep_01',
            tenant_id: 'ten_01',
            trace_id: 'trc_01',
            connection_id: 'conn_01',
            stream: 'meter_reads',
            record_key: 'MTR-77410',
            data_hash: 'dh_01',
            version: 1,
            generation_id: 1,
            last_seen_generation: 1,
            first_seen_at: '2026-10-29T08:00:01Z',
            extracted_at: '2026-10-29T08:00:00Z',
            updated_at: '2026-10-29T08:00:01Z',
            source_inbound_record_id: 'inb_01',
          },
        ],
        replica_rejections: [
          {
            id: 'rrej_01',
            tenant_id: 'ten_01',
            connection_id: 'conn_01',
            stream: 'meter_reads',
            inbound_record_id: 'inb_01',
            record_index: 1,
            reason: 'MISSING_PRIMARY_KEY',
            detail: 'meter_id missing',
            trace_id: 'trc_01',
            created_at: '2026-10-29T08:00:01Z',
          },
        ],
        normalized_records: [
          {
            id: 'nrm_01',
            tenant_id: 'ten_01',
            trace_id: 'trc_01',
            connection_id: 'conn_01',
            canonical_type: 'energy.meter_interval.v1',
            source_id: 'MTR-77410',
            normalized_at: '2026-10-29T08:00:02Z',
          },
        ],
        normalization_rejections: [
          {
            id: 'nrej_01',
            tenant_id: 'ten_01',
            replica_record_id: 'rep_01',
            stream: 'meter_reads',
            transformation_id: 'itron.meter_read.to_gem',
            transformation_version: 1,
            reason_code: 'SCHEMA_MISMATCH',
            field_path: '$.kwh',
            detail: 'Expected numeric kwh',
            trace_id: 'trc_01',
            correlation_id: 'MTR-77410',
            created_at: '2026-10-29T08:00:02Z',
          },
        ],
        entity_mappings: [
          {
            id: 'gem_01',
            tenant_id: 'ten_01',
            trace_id: 'trc_01',
            entity_domain: 'energy.meter',
            canonical_id: 'gem_mtr_01',
            source_connection_id: 'conn_01',
            source_entity_id: 'MTR-77410',
            dest_connection_id: 'conn_mdm',
            dest_entity_id: 'ORA-SP-01',
            created_at: '2026-10-29T08:00:02Z',
          },
        ],
        outbound_records: [
          {
            id: 'out_01',
            tenant_id: 'ten_01',
            trace_id: 'trc_01',
            connection_id: 'conn_mdm',
            app_id: 'oracle_mdm',
            stream_name: 'determinants',
            operation: 'UPSERT',
            target_url: 'https://mdm.example.com/api',
            http_method: 'POST',
            request_size_bytes: 80,
            request_sha256: 'sha_out_01',
            status: 'FAILED',
            attempt_number: 1,
            sent_at: '2026-10-29T08:00:03Z',
          },
        ],
        trace_events: [
          {
            id: 'tev_01',
            tenant_id: 'ten_01',
            trace_id: 'trc_01',
            event_type: 'RECEIVED',
            actor: 'GATEWAY',
            created_at: '2026-10-29T08:00:00Z',
          },
        ],
      },
      'GET /api/v1/tenants/ten_01/ip/transactions/trc_01/lineage': lineageWire,
      'GET /api/v1/tenants/ten_01/ip/transactions/trc_no_inb': {
        trace_id: 'trc_no_inb',
        tenant_id: 'ten_01',
        original_trace_id: 'trc_no_inb',
        replay_count: 0,
        status: 'INGESTED',
        inbound_record: null,
      },
      'POST /api/v1/tenants/ten_01/ip/transactions/trc_01/replay': {
        status: 'QUEUED',
        original_trace_id: 'trc_01',
        parent_trace_id: 'trc_01',
        new_trace_id: 'trc_02',
        stage: 'RETRY_DELIVER',
        replay_count: 1,
        correlation_id: 'MTR-77410',
      },
      'POST /api/v1/tenants/ten_01/ip/transactions/trc_01/modify-and-replay': {
        status: 'QUEUED',
        original_trace_id: 'trc_01',
        parent_trace_id: 'trc_01',
        new_trace_id: 'trc_03',
        stage: 'RETRY_NORMALIZE',
        replay_count: 1,
        correlation_id: 'MTR-77410',
      },
      'POST /api/v1/tenants/ten_01/ip/transactions/bulk-replay': {
        status: 'PARTIAL',
        stage: 'RETRY_DELIVER',
        replayed_count: 1,
        succeeded_trace_ids: ['trc_01'],
        new_trace_ids: ['trc_04'],
        failed_items: [
          {
            trace_id: 'trc_99',
            error_code: 'REPLAY_CAP_EXCEEDED',
            message: 'Cap reached',
          },
        ],
      },
    });

    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local',
      fetchImpl,
      logger,
    });
    const stitchRepo = new HttpStitchRepository(client, logger);
    const traceRepo = new HttpTraceRepository(client, logger);

    expect((await stitchRepo.listDefinitions('ten_01')).ok).toBe(true);
    expect((await stitchRepo.getDefinition('ten_01', 'energy.ami_to_mdm', 1)).ok).toBe(true);
    expect((await stitchRepo.listStitches('ten_01')).ok).toBe(true);
    expect(
      (
        await stitchRepo.registerStitch('ten_01', {
          workflowId: 'energy.ami_to_mdm',
          workflowVersion: 1,
          canonicalEventType: 'energy.meter_interval.v1',
          isTrigger: true,
          idempotencyKeyField: 'source_id',
          isActive: true,
        })
      ).ok,
    ).toBe(true);
    expect(
      (
        await stitchRepo.dispatchEvent('ten_01', {
          canonicalEventType: 'energy.meter_interval.v1',
          payload: { kwh: 10 },
        })
      ).ok,
    ).toBe(true);
    expect((await stitchRepo.listRuns('ten_01', { status: 'SUCCEEDED' })).ok).toBe(true);
    expect((await stitchRepo.getRun('ten_01', 'run_01')).ok).toBe(true);

    expect((await traceRepo.listRecentTraces('ten_01', { minReplayCount: 1 })).ok).toBe(true);
    expect(calls.some((c) => c.url.includes('min_replay_count=1'))).toBe(true);
    expect((await traceRepo.searchByCorrelation('ten_01', 'MTR-77410')).ok).toBe(true);
    const fullTrace = expectOk(await traceRepo.getTrace('ten_01', 'trc_01', true));
    expect(fullTrace.entityMappings[0]?.destEntityId).toBe('ORA-SP-01');
    expect(fullTrace.replicaRejections[0]?.reason).toBe('MISSING_PRIMARY_KEY');
    expect(fullTrace.normalizationRejections[0]?.reasonCode).toBe('SCHEMA_MISMATCH');
    const traceWithoutInbound = expectOk(await traceRepo.getTrace('ten_01', 'trc_no_inb', false));
    expect(traceWithoutInbound.inboundRecord).toBeNull();
    expect((await traceRepo.getTraceLineage('ten_01', 'trc_01')).ok).toBe(true);
    expect(
      (await traceRepo.replayTransaction('ten_01', 'trc_01', ReplayStage.RETRY_DELIVER)).ok,
    ).toBe(true);
    expect(
      (
        await traceRepo.modifyAndReplayTransaction(
          'ten_01',
          'trc_01',
          ReplayStage.RETRY_NORMALIZE,
          { kwh: 50 },
        )
      ).ok,
    ).toBe(true);
    const bulkResult = expectOk(
      await traceRepo.bulkReplayTransactions(
        'ten_01',
        ['trc_01', 'trc_99'],
        ReplayStage.RETRY_DELIVER,
      ),
    );
    expect(bulkResult.failedItems[0]?.errorCode).toBe('REPLAY_CAP_EXCEEDED');
    expect(calls).toHaveLength(15);
  });

  it('emits structured ERROR http_wire.schema_drift log when wire JSON violates Zod contract', async () => {
    const logger = new RecordingLoggerFake().bind({ product: 'ip', tenant_id: 'ten_01' });
    const { fetchImpl } = createRouteFetch({
      'GET /api/v1/ip/catalog/apps': [{ unexpected_key: 123 }],
    });

    const client = new FetchHttpClientAdapter({ baseUrl: 'https://api.soopa.local', fetchImpl });
    const catalogRepo = new HttpCatalogRepository(client, logger);

    const res = await catalogRepo.listApps();
    expect(res.ok).toBe(false);
    if (!res.ok) {
      expect(res.error.code).toBe(ApiErrorCode.SCHEMA_DRIFT);
    }

    expect(logger.entries).toHaveLength(1);
    expect(logger.entries[0]?.level).toBe(LogLevel.ERROR);
    expect(logger.entries[0]?.event).toBe('http_wire.schema_drift');
    expect(logger.entries[0]?.attributes.context).toBe('GET /api/v1/ip/catalog/apps');
    expect(logger.entries[0]?.attributes.tenant_id).toBe('ten_01');
  });
});
