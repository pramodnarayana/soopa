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
  app_id: 'acme_source',
  name: 'Acme Prod',
  auth_type: 'OAUTH2',
  public_config: { base_url: 'https://api.acme.example.com' },
  status: 'ACTIVE',
  connection_fingerprint: 'fp_01',
  created_at: '2026-10-29T08:00:00Z',
  updated_at: '2026-10-29T08:00:00Z',
};

const WIRE_SYNC_RUN = {
  run_id: 'sync_01',
  tenant_id: 'ten_01',
  connection_id: 'conn_01',
  stream_name: 'records_alpha',
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
  stream_name: 'records_alpha',
  cursor_field: 'captured_at',
  cursor_value: '2026-10-29T08:00:00Z',
  records_synced_count: 150,
  last_synced_at: '2026-10-29T08:00:05Z',
};

const WIRE_TRANSFORMATION = {
  id: 'trn_01',
  tenant_id: 'ten_01',
  connection_id: 'conn_01',
  stream: 'records_alpha',
  transformation_id: 'acme.record_alpha.to_gem',
  transformation_version: 1,
  mode: 'SHADOW',
  shadow_transformation_version: 2,
  was_created: true,
};

const WIRE_STITCH_DEFINITION = {
  workflow_id: 'workflow.sync_alpha_to_sink',
  version: 1,
  default_priority: 'HIGH',
  description: 'Source Alpha to Sink',
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
  workflow_id: 'workflow.sync_alpha_to_sink',
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

describe('Outbound HTTP Repositories Wire Contracts', () => {
  it('maps HttpCatalogRepository wire responses', async () => {
    const logger = new RecordingLoggerFake();
    const { fetchImpl, calls } = createRouteFetch({
      'GET /api/v1/tenants/ten_01/ip/catalog/apps': [
        {
          app_id: 'acme_source',
          display_name: 'Acme Source API',
          category: 'api',
          auth_type: 'OAUTH2',
        },
      ],
      'GET /api/v1/tenants/ten_01/ip/catalog/apps/acme_source/spec': {
        app_id: 'acme_source',
        display_name: 'Acme Source API',
        auth_type: 'OAUTH2',
        category: 'api',
        properties: [
          {
            name: 'region',
            label: 'Region',
            type: 'DROPDOWN',
            options: [{ label: 'US West', value: 'us-west-2' }],
            oauth_config: {
              auth_url: 'https://auth.example.com/authorize',
              token_url: 'https://auth.example.com/token',
              scopes: ['records:read'],
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
    });

    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local',
      fetchImpl,
      logger,
    });
    const catalogRepo = new HttpCatalogRepository(client, logger);

    const apps = expectOk(
      await catalogRepo.listApps('ten_01', { category: 'api', search: 'acme' }),
    );
    expect(apps[0]?.appId).toBe('acme_source');

    const spec = expectOk(await catalogRepo.getAppSpec('ten_01', 'acme_source'));
    expect(spec.properties[0]?.oauthConfig?.scopes).toEqual(['records:read']);
    expect(calls).toHaveLength(2);
  });

  it('maps HttpConnectionRepository wire responses across all 8 methods', async () => {
    const logger = new RecordingLoggerFake();
    const { fetchImpl, calls } = createRouteFetch({
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
            name: 'records_alpha',
            fields: [{ name: 'record_id', data_type: 'string', nullable: false }],
            primary_key: ['record_id'],
            cursor_field: 'updated_at',
            supported_sync_modes: ['INCREMENTAL'],
          },
        ],
      },
      'POST /api/v1/tenants/ten_01/ip/connections/conn_01/relink': WIRE_CONNECTION,
      'POST /api/v1/tenants/ten_01/ip/connections/conn_01/deactivate': {
        ...WIRE_CONNECTION,
        status: 'INACTIVE',
      },
      'DELETE /api/v1/tenants/ten_01/ip/connections/conn_01': null,
    });

    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local',
      fetchImpl,
      logger,
    });
    const connRepo = new HttpConnectionRepository(client, logger);

    const listed = expectOk(await connRepo.listConnections('ten_01', 'ACTIVE'));
    expect(listed[0]?.connectionFingerprint).toBe('fp_01');

    const detail = expectOk(await connRepo.getConnection('ten_01', 'conn_01'));
    expect(detail.id).toBe('conn_01');

    const checked = expectOk(
      await connRepo.checkConnection('ten_01', {
        appId: 'acme_source',
        authType: AuthType.OAUTH2,
        publicConfig: { base_url: 'https://api.acme.example.com' },
        rawCredentials: { secret: 'sec_1' },
      }),
    );
    expect(checked.success).toBe(true);

    const created = expectOk(
      await connRepo.createConnection('ten_01', {
        appId: 'acme_source',
        name: 'Acme Prod',
        authType: AuthType.OAUTH2,
        publicConfig: { base_url: 'https://api.acme.example.com' },
        rawCredentials: { secret: 'sec_1' },
      }),
    );
    expect(created.name).toBe('Acme Prod');

    const discovered = expectOk(await connRepo.discoverCatalog('ten_01', 'conn_01'));
    expect(discovered.streams[0]?.fields[0]?.dataType).toBe('string');

    const relinked = expectOk(
      await connRepo.relinkConnection('ten_01', 'conn_01', {
        newName: 'Acme Rotated',
      }),
    );
    expect(relinked.id).toBe('conn_01');

    const deactivated = expectOk(await connRepo.deactivateConnection('ten_01', 'conn_01'));
    expect(deactivated.status).toBe('INACTIVE');

    const deleted = expectOk(await connRepo.deleteConnection('ten_01', 'conn_01'));
    expect(deleted).toBeUndefined();
    expect(calls).toHaveLength(8);
    const deleteCall = calls[calls.length - 1];
    expect(deleteCall?.url).toContain('permanent=true');
  });

  it('maps HttpSyncRunRepository wire responses across all 5 methods', async () => {
    const logger = new RecordingLoggerFake();
    const { fetchImpl, calls } = createRouteFetch({
      'GET /api/v1/tenants/ten_01/ip/connections/conn_01/sync-runs': [WIRE_SYNC_RUN],
      'GET /api/v1/tenants/ten_01/ip/connections/conn_01/sync-runs/sync_01': WIRE_SYNC_RUN,
      'POST /api/v1/tenants/ten_01/ip/connections/conn_01/sync-runs': WIRE_SYNC_RUN,
      'GET /api/v1/tenants/ten_01/ip/connections/conn_01/streams/state': [WIRE_STREAM_STATE],
      'POST /api/v1/tenants/ten_01/ip/connections/conn_01/streams/records_alpha/reset': {
        ...WIRE_STREAM_STATE,
        cursor_value: null,
        records_synced_count: 0,
      },
    });

    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local',
      fetchImpl,
      logger,
    });
    const syncRepo = new HttpSyncRunRepository(client, logger);

    const runs = expectOk(await syncRepo.listSyncRuns('ten_01', 'conn_01'));
    expect(runs[0]?.recordsCount).toBe(150);

    const singleRun = expectOk(await syncRepo.getSyncRun('ten_01', 'conn_01', 'sync_01'));
    expect(singleRun.runId).toBe('sync_01');

    const triggered = expectOk(
      await syncRepo.triggerSyncRun('ten_01', 'conn_01', {
        streamName: 'records_alpha',
        forcedKind: SyncRunKind.FULL_REFRESH,
      }),
    );
    expect(triggered.runId).toBe('sync_01');

    const states = expectOk(await syncRepo.listStreamStates('ten_01', 'conn_01'));
    expect(states[0]?.cursorField).toBe('captured_at');

    const reset = expectOk(
      await syncRepo.resetStreamCheckpoint('ten_01', 'conn_01', 'records_alpha'),
    );
    expect(reset.cursorValue).toBeNull();
    expect(calls).toHaveLength(5);
  });

  it('maps HttpTransformationRepository wire responses across all 6 methods', async () => {
    const logger = new RecordingLoggerFake();
    const { fetchImpl, calls } = createRouteFetch({
      'GET /api/v1/tenants/ten_01/ip/transformations/transformers': [
        {
          transformation_id: 'acme.record_alpha.to_gem',
          transformation_version: 2,
          target_types: ['canonical.record_alpha.v1'],
        },
      ],
      'GET /api/v1/tenants/ten_01/ip/transformations/connections/conn_01': [WIRE_TRANSFORMATION],
      'GET /api/v1/tenants/ten_01/ip/transformations/connections/conn_01/streams/records_alpha':
        WIRE_TRANSFORMATION,
      'PUT /api/v1/tenants/ten_01/ip/transformations/connections/conn_01/streams/records_alpha':
        WIRE_TRANSFORMATION,
      'POST /api/v1/tenants/ten_01/ip/transformations/connections/conn_01/streams/records_alpha/promote':
        {
          id: 'trn_01',
          connection_id: 'conn_01',
          stream: 'records_alpha',
          transformation_id: 'acme.record_alpha.to_gem',
          promoted_version: 2,
          previous_version: 1,
        },
      'POST /api/v1/tenants/ten_01/ip/transformations/preview': {
        transformation_id: 'acme.record_alpha.to_gem',
        transformation_version: 1,
        drafts: [
          {
            canonical_type: 'canonical.record_alpha.v1',
            source_id: 'REC-01',
            fields: { value_num: 12.5 },
            references: [
              {
                field_name: 'parent_entity',
                target_canonical_type: 'canonical.parent_entity.v1',
                target_source_id: 'PE-01',
              },
            ],
          },
        ],
        rejections: [{ reason: 'WARN_OPTIONAL', field_path: '$.score', detail: 'Missing' }],
        shadow_transformation_version: 2,
        shadow_diffs: { value_num: { active: 12.5, shadow: 12.5 } },
      },
    });

    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local',
      fetchImpl,
      logger,
    });
    const transRepo = new HttpTransformationRepository(client, logger);

    const transformers = expectOk(await transRepo.listRegisteredTransformers('ten_01'));
    expect(transformers[0]?.transformationVersion).toBe(2);

    const connTrans = expectOk(await transRepo.listConnectionTransformations('ten_01', 'conn_01'));
    expect(connTrans[0]?.shadowTransformationVersion).toBe(2);

    const streamTrans = expectOk(
      await transRepo.getStreamTransformation('ten_01', 'conn_01', 'records_alpha'),
    );
    expect(streamTrans.wasCreated).toBe(true);

    const bound = expectOk(
      await transRepo.bindStreamTransformation('ten_01', 'conn_01', 'records_alpha', {
        transformationId: 'acme.record_alpha.to_gem',
        transformationVersion: 1,
        mode: TransformationMode.SHADOW,
        shadowTransformationVersion: 2,
      }),
    );
    expect(bound.id).toBe('trn_01');

    const boundActive = expectOk(
      await transRepo.bindStreamTransformation('ten_01', 'conn_01', 'records_alpha', {
        transformationId: 'acme.record_alpha.to_gem',
        transformationVersion: 2,
        mode: TransformationMode.ACTIVE,
      }),
    );
    expect(boundActive.id).toBe('trn_01');

    const promoted = expectOk(
      await transRepo.promoteShadowVersion('ten_01', 'conn_01', 'records_alpha'),
    );
    expect(promoted.promotedVersion).toBe(2);

    const preview = expectOk(
      await transRepo.previewTransformation('ten_01', {
        connectionId: 'conn_01',
        stream: 'records_alpha',
        transformationId: 'acme.record_alpha.to_gem',
        transformationVersion: 1,
        recordKey: 'REC-01',
        samplePayload: { value_num: 12.5 },
      }),
    );
    expect(preview.drafts[0]?.references[0]?.targetSourceId).toBe('PE-01');
    expect(calls).toHaveLength(7);
  });

  it('maps HttpStitchRepository wire responses across all 7 methods', async () => {
    const logger = new RecordingLoggerFake();
    const { fetchImpl, calls } = createRouteFetch({
      'GET /api/v1/tenants/ten_01/ip/stitches/definitions': [WIRE_STITCH_DEFINITION],
      'GET /api/v1/tenants/ten_01/ip/stitches/definitions/workflow.sync_alpha_to_sink':
        WIRE_STITCH_DEFINITION,
      'GET /api/v1/tenants/ten_01/ip/stitches': [
        {
          id: 'stc_01',
          tenant_id: 'ten_01',
          workflow_id: 'workflow.sync_alpha_to_sink',
          workflow_version: 1,
          canonical_event_type: 'canonical.record_alpha.v1',
          is_trigger: true,
          idempotency_key_field: 'source_id',
          is_active: true,
        },
      ],
      'POST /api/v1/tenants/ten_01/ip/stitches': {
        id: 'stc_02',
        tenant_id: 'ten_01',
        workflow_id: 'workflow.sync_alpha_to_sink',
        workflow_version: 1,
        canonical_event_type: 'canonical.record_alpha.v1',
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
    });

    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local',
      fetchImpl,
      logger,
    });
    const stitchRepo = new HttpStitchRepository(client, logger);

    expect((await stitchRepo.listDefinitions('ten_01')).ok).toBe(true);
    expect((await stitchRepo.getDefinition('ten_01', 'workflow.sync_alpha_to_sink', 1)).ok).toBe(
      true,
    );
    expect((await stitchRepo.listStitches('ten_01')).ok).toBe(true);
    expect(
      (
        await stitchRepo.registerStitch('ten_01', {
          workflowId: 'workflow.sync_alpha_to_sink',
          workflowVersion: 1,
          canonicalEventType: 'canonical.record_alpha.v1',
          isTrigger: true,
          idempotencyKeyField: 'source_id',
          isActive: true,
        })
      ).ok,
    ).toBe(true);
    expect(
      (
        await stitchRepo.dispatchEvent('ten_01', {
          canonicalEventType: 'canonical.record_alpha.v1',
          payload: { value_num: 10 },
        })
      ).ok,
    ).toBe(true);
    expect((await stitchRepo.listRuns('ten_01', { status: 'SUCCEEDED' })).ok).toBe(true);
    expect((await stitchRepo.getRun('ten_01', 'run_01')).ok).toBe(true);
    expect(calls).toHaveLength(7);
  });

  it('maps HttpTraceRepository wire responses across all 7 methods', async () => {
    const logger = new RecordingLoggerFake();
    const lineageWire = [
      {
        trace_id: 'trc_01',
        correlation_id: 'REC-77410',
        status: 'FAILED',
        primary_layer: 'L5_DELIVERY',
        created_at: '2026-10-29T08:00:00Z',
        replay_count: 0,
        parent_trace_id: null,
        original_trace_id: 'trc_01',
      },
    ];
    const { fetchImpl, calls } = createRouteFetch({
      'GET /api/v1/tenants/ten_01/ip/traces': lineageWire,
      'GET /api/v1/tenants/ten_01/ip/traces/search': lineageWire,
      'GET /api/v1/tenants/ten_01/ip/traces/trc_01': {
        trace_id: 'trc_01',
        tenant_id: 'ten_01',
        correlation_id: 'REC-77410',
        original_trace_id: 'trc_01',
        parent_trace_id: null,
        replay_count: 0,
        status: 'FAILED',
        inbound_record: {
          id: 'inb_01',
          tenant_id: 'ten_01',
          trace_id: 'trc_01',
          connection_id: 'conn_01',
          app_id: 'acme_source',
          stream_name: 'records_alpha',
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
            stream: 'records_alpha',
            record_key: 'REC-77410',
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
            stream: 'records_alpha',
            inbound_record_id: 'inb_01',
            record_index: 1,
            reason: 'MISSING_PRIMARY_KEY',
            detail: 'record_id missing',
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
            canonical_type: 'canonical.record_alpha.v1',
            source_id: 'REC-77410',
            normalized_at: '2026-10-29T08:00:02Z',
          },
        ],
        normalization_rejections: [
          {
            id: 'nrej_01',
            tenant_id: 'ten_01',
            replica_record_id: 'rep_01',
            stream: 'records_alpha',
            transformation_id: 'acme.record_alpha.to_gem',
            transformation_version: 1,
            reason_code: 'SCHEMA_MISMATCH',
            field_path: '$.value_num',
            detail: 'Expected numeric value_num',
            trace_id: 'trc_01',
            correlation_id: 'REC-77410',
            created_at: '2026-10-29T08:00:02Z',
          },
        ],
        entity_mappings: [
          {
            id: 'gem_01',
            tenant_id: 'ten_01',
            trace_id: 'trc_01',
            entity_domain: 'domain.record_alpha',
            canonical_id: 'gem_rec_01',
            source_connection_id: 'conn_01',
            source_entity_id: 'REC-77410',
            dest_connection_id: 'conn_globex',
            dest_entity_id: 'GLX-ENT-01',
            created_at: '2026-10-29T08:00:02Z',
          },
        ],
        outbound_records: [
          {
            id: 'out_01',
            tenant_id: 'ten_01',
            trace_id: 'trc_01',
            connection_id: 'conn_globex',
            app_id: 'globex_dest',
            stream_name: 'canonical_sink',
            operation: 'UPSERT',
            target_url: 'https://globex.example.com/api',
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
      'GET /api/v1/tenants/ten_01/ip/traces/trc_01/lineage': lineageWire,
      'GET /api/v1/tenants/ten_01/ip/traces/trc_no_inb': {
        trace_id: 'trc_no_inb',
        tenant_id: 'ten_01',
        original_trace_id: 'trc_no_inb',
        replay_count: 0,
        status: 'INGESTED',
        inbound_record: null,
      },
      'POST /api/v1/tenants/ten_01/ip/traces/trc_01/replay': {
        status: 'QUEUED',
        original_trace_id: 'trc_01',
        parent_trace_id: 'trc_01',
        new_trace_id: 'trc_02',
        stage: 'RETRY_DELIVER',
        replay_count: 1,
        correlation_id: 'REC-77410',
      },
      'POST /api/v1/tenants/ten_01/ip/traces/trc_01/modify-and-replay': {
        status: 'QUEUED',
        original_trace_id: 'trc_01',
        parent_trace_id: 'trc_01',
        new_trace_id: 'trc_03',
        stage: 'RETRY_NORMALIZE',
        replay_count: 1,
        correlation_id: 'REC-77410',
      },
      'POST /api/v1/tenants/ten_01/ip/traces/bulk-replay': {
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
    const traceRepo = new HttpTraceRepository(client, logger);

    expect((await traceRepo.listRecentTraces('ten_01', { minReplayCount: 1 })).ok).toBe(true);
    expect(calls.some((c) => c.url.includes('min_replay_count=1'))).toBe(true);
    expect((await traceRepo.searchByCorrelation('ten_01', 'REC-77410')).ok).toBe(true);
    const fullTrace = expectOk(await traceRepo.getTrace('ten_01', 'trc_01', true));
    expect(fullTrace.entityMappings[0]?.destEntityId).toBe('GLX-ENT-01');
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
          { value_num: 50 },
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
    expect(calls).toHaveLength(8);
  });

  it('emits structured ERROR http_wire.schema_drift log when wire JSON violates Zod contract', async () => {
    const logger = new RecordingLoggerFake().bind({ product: 'ip', tenant_id: 'ten_01' });
    const { fetchImpl } = createRouteFetch({
      'GET /api/v1/tenants/ten_01/ip/catalog/apps': [{ unexpected_key: 123 }],
    });

    const client = new FetchHttpClientAdapter({ baseUrl: 'https://api.soopa.local', fetchImpl });
    const catalogRepo = new HttpCatalogRepository(client, logger);

    const res = await catalogRepo.listApps('ten_01');
    expect(res.ok).toBe(false);
    if (!res.ok) {
      expect(res.error.code).toBe(ApiErrorCode.SCHEMA_DRIFT);
    }

    expect(logger.entries).toHaveLength(1);
    expect(logger.entries[0]?.level).toBe(LogLevel.ERROR);
    expect(logger.entries[0]?.event).toBe('http_wire.schema_drift');
    expect(logger.entries[0]?.attributes.context).toBe(
      'GET /api/v1/tenants/ten_01/ip/catalog/apps',
    );
    expect(logger.entries[0]?.attributes.tenant_id).toBe('ten_01');
  });
});
