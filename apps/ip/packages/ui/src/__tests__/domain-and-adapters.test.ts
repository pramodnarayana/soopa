import { ApiErrorCode, FetchHttpClientAdapter } from '@soopa/ui';
import { describe, expect, it } from 'vitest';
import { HttpConnectionRepository } from '../adapters/http/repositories/http-connection.repository';
import { HttpStitchRepository } from '../adapters/http/repositories/http-stitch.repository';
import { HttpTraceRepository } from '../adapters/http/repositories/http-trace.repository';
import { HttpTransformationRepository } from '../adapters/http/repositories/http-transformation.repository';
import { normalizeAuthType } from '../domain/catalog-auth';
import { computeDagLayout } from '../domain/dag/compute-dag-layout';
import {
  AuthType,
  ConnectionHandshakeStatus,
  ConnectorDirection,
  IP_PRODUCT_THEME_TOKEN,
  isAuthTypeValue,
  isReplayStageValue,
  isTransformationModeValue,
  PipelineLayer,
  ReplayDispatchStatus,
  ReplayStage,
  StagePosture,
  TransformationMode,
} from '../domain/enums';
import {
  computePipelineWaterfallSummary,
  deriveEligibleReplayStages,
  extractModifiablePayloadSeed,
} from '../domain/replay/derive-replay-eligibility';
import { isPlainJsonRecord, parseJsonObject } from '../domain/replay/parse-json-object';
import { buildRegisterStitchInput } from '../domain/stitch-registration';
import type { IpTrace } from '../domain/trace';

describe('IP Domain: computeDagLayout', () => {
  it('assigns topological ranks and deterministic coordinates for multi-branch Stitch DAGs', () => {
    const layout = computeDagLayout([
      {
        nodeKey: 'query_meter_replica',
        kind: 'TASK',
        stepType: 'query_replica',
        parents: [],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'ip.default',
      },
      {
        nodeKey: 'await_tariff_approval',
        kind: 'WAIT_FOR_EVENT',
        stepType: 'wait_signal',
        parents: ['query_meter_replica'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: 'energy.tariff.approved',
        queueName: 'ip.default',
      },
      {
        nodeKey: 'push_erp_invoice',
        kind: 'TASK',
        stepType: 'execute_http_action',
        parents: ['await_tariff_approval'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'IDEMPOTENT_EXTERNAL',
        waitEventKey: null,
        queueName: 'ip.delivery',
      },
      {
        nodeKey: 'notify_ops_on_failure',
        kind: 'TASK',
        stepType: 'emit_notification',
        parents: ['push_erp_invoice'],
        edgeCondition: 'ON_FAILURE',
        effectPolicy: 'IDEMPOTENT_EXTERNAL',
        waitEventKey: null,
        queueName: 'ip.default',
      },
    ]);

    expect(layout.nodes).toHaveLength(4);
    expect(layout.edges).toHaveLength(3);

    const byKey = new Map(layout.nodes.map((node) => [node.node.nodeKey, node]));
    expect(byKey.get('query_meter_replica')?.rank).toBe(0);
    expect(byKey.get('await_tariff_approval')?.rank).toBe(1);
    expect(byKey.get('push_erp_invoice')?.rank).toBe(2);
    expect(byKey.get('notify_ops_on_failure')?.rank).toBe(3);
    expect(layout.width).toBeGreaterThan(800);
    expect(layout.height).toBeGreaterThan(140);
  });

  it('safely breaks cycles without hanging if malformed graph metadata is encountered', () => {
    const layout = computeDagLayout([
      {
        nodeKey: 'step_a',
        kind: 'TASK',
        stepType: 'query_replica',
        parents: ['step_b'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'ip.default',
      },
      {
        nodeKey: 'step_b',
        kind: 'SLEEP',
        stepType: 'sleep',
        parents: ['step_a'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'ip.default',
      },
    ]);

    expect(layout.nodes).toHaveLength(2);
    expect(layout.edges).toHaveLength(2);
  });
});

describe('IP Domain: Replay Eligibility & 5-Layer Waterfall Summary', () => {
  const sampleFailedTrace: IpTrace = {
    traceId: 'ip_trc_101',
    tenantId: 'ten_01',
    correlationId: 'MTR-700',
    originalTraceId: 'ip_trc_100',
    parentTraceId: 'ip_trc_100',
    replayCount: 1,
    status: 'FAILED',
    inboundRecord: {
      id: 'inb_01',
      tenantId: 'ten_01',
      traceId: 'ip_trc_101',
      correlationId: 'MTR-700',
      parentTraceId: 'ip_trc_100',
      originalTraceId: 'ip_trc_100',
      replayCount: 1,
      connectionId: 'conn_itron',
      appId: 'itron_mdm',
      streamName: 'meter_readings',
      ingestionMode: 'PUSH_WEBHOOK',
      syncRunId: null,
      generationId: null,
      externalEventId: 'evt_700',
      requestHeaders: { 'x-signature': '[REDACTED]' },
      requestBody: null,
      requestS3Key: 's3://ip-payloads/ten_01/inb_01.json',
      requestSizeBytes: 131072,
      requestSha256: 'abc123',
      responseStatusCode: 202,
      responseHeaders: null,
      responseBody: { accepted: true },
      responseS3Key: null,
      durationMs: 12,
      receivedAt: '2026-10-29T08:00:00Z',
    },
    replicaRecords: [
      {
        id: 'rep_01',
        tenantId: 'ten_01',
        traceId: 'ip_trc_101',
        correlationId: 'MTR-700',
        parentTraceId: 'ip_trc_100',
        originalTraceId: 'ip_trc_100',
        replayCount: 1,
        connectionId: 'conn_itron',
        stream: 'meter_readings',
        recordKey: 'MTR-700',
        primaryKeyValues: ['MTR-700'],
        cursorValue: '2026-10-29T08:00:00Z',
        cursorKind: 'TIMESTAMP',
        data: { meter_id: 'MTR-700', kwh: 42.5 },
        dataHash: 'hash_01',
        version: 1,
        generationId: 1,
        lastSeenGeneration: 1,
        firstSeenAt: '2026-10-29T08:00:00Z',
        extractedAt: '2026-10-29T08:00:00Z',
        updatedAt: '2026-10-29T08:00:00Z',
        deletedAt: null,
        sourceInboundRecordId: 'inb_01',
      },
    ],
    replicaRejections: [],
    normalizedRecords: [
      {
        id: 'nrm_01',
        tenantId: 'ten_01',
        traceId: 'ip_trc_101',
        correlationId: 'MTR-700',
        parentTraceId: 'ip_trc_100',
        originalTraceId: 'ip_trc_100',
        replayCount: 1,
        connectionId: 'conn_itron',
        canonicalType: 'energy.mdm_meter_reading',
        sourceId: 'MTR-700',
        canonicalData: {
          meter_serial_number: 'MTR-700',
          kwh_delivered: '42.5',
          extensions: { firmware: '4.2' },
        },
        normalizedAt: '2026-10-29T08:00:01Z',
      },
    ],
    normalizationRejections: [],
    entityMappings: [
      {
        id: 'gem_01',
        tenantId: 'ten_01',
        traceId: 'ip_trc_101',
        correlationId: 'MTR-700',
        parentTraceId: 'ip_trc_100',
        originalTraceId: 'ip_trc_100',
        replayCount: 1,
        entityDomain: 'energy.meter_reading',
        canonicalId: 'can_mtr_700',
        sourceConnectionId: 'conn_itron',
        sourceEntityId: 'MTR-700',
        destConnectionId: 'conn_sap',
        destEntityId: null,
        createdAt: '2026-10-29T08:00:01Z',
      },
    ],
    outboundRecords: [
      {
        id: 'out_01',
        tenantId: 'ten_01',
        traceId: 'ip_trc_101',
        correlationId: 'MTR-700',
        parentTraceId: 'ip_trc_100',
        originalTraceId: 'ip_trc_100',
        replayCount: 1,
        connectionId: 'conn_sap',
        appId: 'sap_s4hana',
        streamName: 'meter_billing',
        operation: 'UPSERT',
        idempotencyKey: 'idem_01',
        externalRecordId: null,
        targetUrl: 'https://sap.example.com/api/readings',
        httpMethod: 'POST',
        requestHeaders: { authorization: '[REDACTED]' },
        requestBody: { meter: 'MTR-700', kwh: '42.5' },
        requestS3Key: null,
        requestSizeBytes: 64,
        requestSha256: 'def456',
        status: 'FAILED',
        responseStatusCode: 429,
        responseHeaders: { 'retry-after': '30' },
        responseBody: { error: 'rate_limit_exceeded' },
        responseS3Key: null,
        durationMs: 185,
        attemptNumber: 3,
        failureCategory: 'RATE_LIMITED',
        retryAfterSeconds: 30,
        errorMessage: '429 Too Many Requests',
        sentAt: '2026-10-29T08:00:02Z',
      },
    ],
    traceEvents: [],
  };

  it('derives eligible deterministic replay stages, Modify & Replay targets, and recommended stage', () => {
    const eligibility = deriveEligibleReplayStages(sampleFailedTrace);
    expect(eligibility.stages).toEqual([
      ReplayStage.RETRY_INGEST,
      ReplayStage.RETRY_NORMALIZE,
      ReplayStage.RETRY_STITCH,
      ReplayStage.RETRY_DELIVER,
    ]);
    expect(eligibility.modifiableStages).toEqual([
      ReplayStage.RETRY_INGEST,
      ReplayStage.RETRY_STITCH,
    ]);
    expect(eligibility.recommendedStage).toBe(ReplayStage.RETRY_DELIVER);
  });

  it('computes 5-layer waterfall posture and detects unhydrated S3 payloads', () => {
    const summary = computePipelineWaterfallSummary(sampleFailedTrace);
    expect(summary.hasUnhydratedS3Payloads).toBe(true);
    const byLayer = new Map(summary.layers.map((layer) => [layer.layer, layer]));
    expect(byLayer.get(PipelineLayer.L1_INGEST)?.posture).toBe(StagePosture.HEALTHY);
    expect(byLayer.get(PipelineLayer.L2_REPLICA)?.posture).toBe(StagePosture.HEALTHY);
    expect(byLayer.get(PipelineLayer.L3_NORMALIZE)?.posture).toBe(StagePosture.HEALTHY);
    expect(byLayer.get(PipelineLayer.L5_DELIVER)?.posture).toBe(StagePosture.CRITICAL);
  });

  it('handles rejection branches, delivered/pending outbound postures, S3 response keys, and payload seeds', () => {
    expect(extractModifiablePayloadSeed(sampleFailedTrace, ReplayStage.RETRY_INGEST)).toEqual({});
    expect(extractModifiablePayloadSeed(sampleFailedTrace, ReplayStage.RETRY_STITCH)).toMatchObject(
      {
        meter_serial_number: 'MTR-700',
      },
    );

    const emptyTrace: IpTrace = {
      ...sampleFailedTrace,
      inboundRecord: null,
      replicaRecords: [],
      replicaRejections: [],
      normalizedRecords: [],
      normalizationRejections: [],
      entityMappings: [],
      outboundRecords: [],
      traceEvents: [],
    };
    const emptyElig = deriveEligibleReplayStages(emptyTrace);
    expect(emptyElig.stages).toEqual([]);
    expect(emptyElig.recommendedStage).toBeNull();
    expect(computePipelineWaterfallSummary(emptyTrace).hasUnhydratedS3Payloads).toBe(false);

    const normRejectedTrace: IpTrace = {
      ...sampleFailedTrace,
      outboundRecords: [],
      normalizationRejections: [
        {
          id: 'nrej_1',
          tenantId: 'ten_01',
          traceId: 'ip_trc_101',
          correlationId: 'MTR-700',
          replicaRecordId: 'rep_01',
          stream: 'meter_readings',
          transformationId: 'itron.v1',
          transformationVersion: 1,
          reasonCode: 'SCHEMA_INVALID',
          fieldPath: '$.kwh',
          detail: 'Negative reading',
          createdAt: '2026-10-29T08:00:01Z',
        },
      ],
      traceEvents: [
        {
          id: 'ev_1',
          tenantId: 'ten_01',
          traceId: 'ip_trc_101',
          correlationId: 'MTR-700',
          eventType: 'stitch.dispatched',
          actor: 'ORCHESTRATOR',
          metadata: null,
          createdAt: '2026-10-29T08:00:02Z',
        },
      ],
    };
    expect(deriveEligibleReplayStages(normRejectedTrace).recommendedStage).toBe(
      ReplayStage.RETRY_NORMALIZE,
    );
    const normSummary = computePipelineWaterfallSummary(normRejectedTrace);
    const normMap = new Map(normSummary.layers.map((l) => [l.layer, l]));
    expect(normMap.get(PipelineLayer.L3_NORMALIZE)?.posture).toBe(StagePosture.CRITICAL);
    expect(normMap.get(PipelineLayer.L4_STITCH)?.posture).toBe(StagePosture.HEALTHY);
    expect(normMap.get(PipelineLayer.L5_DELIVER)?.posture).toBe(StagePosture.SKIPPED);

    const baseInbound = sampleFailedTrace.inboundRecord;
    const baseOutbound = sampleFailedTrace.outboundRecords[0];
    if (!baseInbound || !baseOutbound) {
      throw new Error('Expected seed inbound and outbound records');
    }

    const repRejectedTrace: IpTrace = {
      ...emptyTrace,
      inboundRecord: {
        ...baseInbound,
        requestBody: { raw: 1 },
        requestS3Key: null,
      },
      replicaRejections: [
        {
          id: 'rrej_1',
          tenantId: 'ten_01',
          traceId: 'ip_trc_101',
          connectionId: 'conn_itron',
          stream: 'meter_readings',
          inboundRecordId: 'inb_01',
          recordIndex: 0,
          reason: 'MISSING_PK',
          detail: 'meter_id missing',
          createdAt: '2026-10-29T08:00:01Z',
        },
      ],
      outboundRecords: [
        {
          ...baseOutbound,
          status: 'DELIVERED',
          failureCategory: null,
          responseBody: null,
          responseS3Key: 's3://ip/resp.json',
        },
      ],
    };
    expect(deriveEligibleReplayStages(repRejectedTrace).recommendedStage).toBe(
      ReplayStage.RETRY_INGEST,
    );
    const repSummary = computePipelineWaterfallSummary(repRejectedTrace);
    expect(repSummary.hasUnhydratedS3Payloads).toBe(true);
    const repMap = new Map(repSummary.layers.map((l) => [l.layer, l]));
    expect(repMap.get(PipelineLayer.L2_REPLICA)?.posture).toBe(StagePosture.CRITICAL);
    expect(repMap.get(PipelineLayer.L5_DELIVER)?.posture).toBe(StagePosture.HEALTHY);
  });
});

function resolveRequestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') {
    return input;
  }
  if (input instanceof URL) {
    return input.href;
  }
  return input.url;
}

const FAKE_JSON_HEADERS = { 'Content-Type': 'application/json' } as const;

const FAKE_ROUTE_FIXTURES: ReadonlyArray<{
  readonly matches: (url: string) => boolean;
  readonly payload: unknown;
}> = [
  {
    matches: (url) => url.includes('/transactions/search'),
    payload: [
      {
        trace_id: 'ip_trc_700',
        correlation_id: 'MTR-700',
        status: 'DELIVERED',
        primary_layer: 'L5_DELIVER',
        created_at: '2026-10-29T08:10:00Z',
        replay_count: 1,
        parent_trace_id: 'ip_trc_699',
        original_trace_id: 'ip_trc_699',
      },
    ],
  },
  {
    matches: (url) => url.endsWith('/connections/check'),
    payload: {
      success: true,
      status: 'ACTIVE',
      message: 'Authenticated with Itron MDM v2',
      error_code: null,
    },
  },
  {
    matches: (url) => url.endsWith('/transformations/preview'),
    payload: {
      transformation_id: 'energy.ami_meter_reading',
      transformation_version: 1,
      drafts: [
        {
          canonical_type: 'energy.mdm_meter_reading',
          source_id: 'MTR-700',
          fields: { kwh_delivered: '88.4' },
          extensions: { channel: 'A' },
          references: [],
        },
      ],
      rejections: [],
      shadow_transformation_version: 2,
      shadow_diffs: {
        'energy.mdm_meter_reading:MTR-700': {
          active: { kwh_delivered: '88.4' },
          shadow: { kwh_delivered: '88.400', unit: 'KWH' },
        },
      },
    },
  },
  {
    matches: (url) => url.includes('/stitches/runs'),
    payload: [
      {
        run_id: 'wfr_01',
        tenant_id: 'ten_01',
        workflow_id: 'energy.meter_reading_erp_sync_stitch',
        workflow_version: 1,
        status: 'RUNNING',
        priority: 'HIGH',
        concurrency_key: 'MTR-700',
        idempotency_key: 'idem_700',
        trace_id: 'ip_trc_700',
        correlation_id: 'MTR-700',
        failure_code: null,
        failure_detail: null,
        created_at: '2026-10-29T08:10:00Z',
        started_at: '2026-10-29T08:10:01Z',
        finished_at: null,
        steps: [
          {
            step_run_id: 'stp_01',
            node_key: 'push_erp',
            status: 'SUCCEEDED',
            retry_count: 1,
            app_retry_count: 0,
            internal_retry_count: 1,
            iteration_count: 1,
            failure_code: null,
            failure_detail: null,
            created_at: '2026-10-29T08:10:01Z',
            finished_at: '2026-10-29T08:10:02Z',
          },
        ],
      },
    ],
  },
];

function resolveFakeResponse(url: string): Response {
  const matched = FAKE_ROUTE_FIXTURES.find((entry) => entry.matches(url));
  if (!matched) {
    return new Response(JSON.stringify({ detail: 'Not found' }), { status: 404 });
  }
  return new Response(JSON.stringify(matched.payload), {
    status: 200,
    headers: FAKE_JSON_HEADERS,
  });
}

function createRecordedTestClient() {
  const recordedHeaders: Array<{ url: string; method: string; idempotencyKey: string | null }> = [];
  const fakeFetch: typeof fetch = async (input, init) => {
    const url = resolveRequestUrl(input);
    const method = init?.method ?? 'GET';
    const headers = new Headers(init?.headers);
    recordedHeaders.push({
      url,
      method,
      idempotencyKey: headers.get('Idempotency-Key'),
    });
    return resolveFakeResponse(url);
  };
  const client = new FetchHttpClientAdapter({
    baseUrl: 'https://cp.soopa.local',
    fetchImpl: fakeFetch,
  });
  return { client, recordedHeaders };
}

describe('IP HTTP Repositories + Zod Schemas + Mappers (Narrow Integration)', () => {
  it('maps correlation search and pre-flight connection check with Idempotency-Key', async () => {
    const { client, recordedHeaders } = createRecordedTestClient();

    const traceRepo = new HttpTraceRepository(client);
    const searchRes = await traceRepo.searchByCorrelation('ten_01', 'MTR-700', 25);
    expect(searchRes.ok).toBe(true);
    if (searchRes.ok) {
      expect(searchRes.value[0]).toMatchObject({ traceId: 'ip_trc_700', replayCount: 1 });
    }

    const connRepo = new HttpConnectionRepository(client);
    const checkRes = await connRepo.checkConnection('ten_01', {
      appId: 'itron_mdm',
      authType: AuthType.OAUTH2,
      publicConfig: { base_url: 'https://mdm.example.com' },
      rawCredentials: { client_secret: 'sec_123' },
    });
    expect(checkRes.ok).toBe(true);
    if (checkRes.ok) {
      expect(checkRes.value.success).toBe(true);
    }

    const postCalls = recordedHeaders.filter((c) => c.method === 'POST');
    expect(postCalls).toHaveLength(1);
    expect(postCalls[0]?.idempotencyKey).toBeTruthy();
  });

  it('maps transformation shadow preview and stitch run retry telemetry', async () => {
    const { client, recordedHeaders } = createRecordedTestClient();

    const transformRepo = new HttpTransformationRepository(client);
    const previewRes = await transformRepo.previewTransformation('ten_01', {
      connectionId: 'conn_itron',
      stream: 'meter_readings',
      transformationId: 'energy.ami_meter_reading',
      transformationVersion: 1,
      recordKey: 'MTR-700',
      samplePayload: { meter_id: 'MTR-700', kwh: 88.4 },
      shadowTransformationVersion: 2,
    });
    expect(previewRes.ok).toBe(true);
    if (previewRes.ok) {
      expect(previewRes.value.drafts).toHaveLength(1);
      expect(previewRes.value.shadowTransformationVersion).toBe(2);
    }

    const stitchRepo = new HttpStitchRepository(client);
    const runsRes = await stitchRepo.listRuns('ten_01', { limit: 10 });
    expect(runsRes.ok).toBe(true);
    if (runsRes.ok) {
      expect(runsRes.value[0]?.steps[0]).toMatchObject({
        internalRetryCount: 1,
        appRetryCount: 0,
      });
    }

    const postCalls = recordedHeaders.filter((c) => c.method === 'POST');
    expect(postCalls).toHaveLength(1);
    expect(postCalls[0]?.idempotencyKey).toBeTruthy();
  });

  it('returns structured SCHEMA_DRIFT Result error instead of throwing when wire payload drifts', async () => {
    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://cp.soopa.local',
      fetchImpl: async () =>
        new Response(JSON.stringify([{ unexpected_wire_shape: true }]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    });

    const traceRepo = new HttpTraceRepository(client);
    const res = await traceRepo.listRecentTraces('ten_01');
    expect(res.ok).toBe(false);
    if (!res.ok) {
      expect(res.error.code).toBe(ApiErrorCode.SCHEMA_DRIFT);
    }
  });
});

describe('IP Domain: Enum Type Guards, JSON Object Parser, Auth Normalization & Stitch Builder', () => {
  it('validates domain enum tokens and rejects unknown strings without unsafe type casts', () => {
    expect(IP_PRODUCT_THEME_TOKEN).toBe('ip');
    expect(ConnectorDirection.BIDIRECTIONAL).toBe('BIDIRECTIONAL');
    expect(ConnectorDirection.SOURCE).toBe('SOURCE');
    expect(ConnectorDirection.DESTINATION).toBe('DESTINATION');
    expect(ConnectionHandshakeStatus.VERIFIED).toBe('VERIFIED');
    expect(ConnectionHandshakeStatus.AUTH_FAILED).toBe('AUTH_FAILED');
    expect(ReplayDispatchStatus.QUEUED).toBe('QUEUED');
    expect(ReplayDispatchStatus.COMPLETED).toBe('COMPLETED');
    expect(ReplayDispatchStatus.PARTIAL).toBe('PARTIAL');

    expect(isAuthTypeValue(AuthType.OAUTH2)).toBe(true);
    expect(isAuthTypeValue('CUSTOM_UNKNOWN')).toBe(false);
    expect(normalizeAuthType(AuthType.BEARER)).toBe(AuthType.BEARER);
    expect(normalizeAuthType('UNRECOGNIZED')).toBe(AuthType.API_KEY);

    expect(isReplayStageValue(ReplayStage.RETRY_DELIVER)).toBe(true);
    expect(isReplayStageValue('INVALID_STAGE')).toBe(false);

    expect(isTransformationModeValue(TransformationMode.SHADOW)).toBe(true);
    expect(isTransformationModeValue('DRAFT')).toBe(false);
  });

  it('parses plain JSON objects and rejects arrays, primitives, null, and malformed JSON', () => {
    expect(isPlainJsonRecord({ meter_id: 'MTR-700' })).toBe(true);
    expect(isPlainJsonRecord(null)).toBe(false);
    expect(isPlainJsonRecord(['a'])).toBe(false);
    expect(isPlainJsonRecord('str')).toBe(false);

    const valid = parseJsonObject('{"meter_id":"MTR-700","kwh":42.5}');
    expect(valid).toEqual({ ok: true, value: { meter_id: 'MTR-700', kwh: 42.5 } });

    const arrayRejected = parseJsonObject('[1, 2, 3]');
    expect(arrayRejected.ok).toBe(false);
    if (!arrayRejected.ok) {
      expect(arrayRejected.reason).toContain('JSON object');
    }

    const nullRejected = parseJsonObject('null');
    expect(nullRejected.ok).toBe(false);

    const invalidSyntax = parseJsonObject('{bad json');
    expect(invalidSyntax.ok).toBe(false);
    if (!invalidSyntax.ok) {
      expect(invalidSyntax.reason.length).toBeGreaterThan(0);
    }
  });

  it('normalizes RegisterStitchInput for trigger vs wait-condition bindings', () => {
    expect(
      buildRegisterStitchInput({
        workflowId: '  ',
        workflowVersion: 1,
        canonicalEventType: 'energy.meter_interval.v1',
        isTrigger: true,
        conditionKey: '',
        idempotencyField: 'source_id',
        concurrencyField: '',
      }),
    ).toBeNull();

    const triggerInput = buildRegisterStitchInput({
      workflowId: 'energy.ami_to_mdm',
      workflowVersion: 2,
      canonicalEventType: ' energy.meter_interval.v1 ',
      isTrigger: true,
      conditionKey: 'ignored_when_trigger',
      idempotencyField: ' source_id ',
      concurrencyField: '   ',
    });
    expect(triggerInput).toEqual({
      workflowId: 'energy.ami_to_mdm',
      workflowVersion: 2,
      canonicalEventType: 'energy.meter_interval.v1',
      isTrigger: true,
      conditionEventKey: null,
      idempotencyKeyField: 'source_id',
      concurrencyKeyField: null,
      isActive: true,
    });

    const signalInput = buildRegisterStitchInput({
      workflowId: 'energy.ami_to_mdm',
      workflowVersion: 1,
      canonicalEventType: 'energy.tariff.approved',
      isTrigger: false,
      conditionKey: ' tariff_gate ',
      idempotencyField: 'source_id',
      concurrencyField: ' meter_id ',
    });
    expect(signalInput?.conditionEventKey).toBe('tariff_gate');
    expect(signalInput?.concurrencyKeyField).toBe('meter_id');
  });
});
