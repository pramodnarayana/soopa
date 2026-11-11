import { describe, expect, it } from 'vitest';
import { normalizeConnectorPropertyType } from '../adapters/http/mappers/catalog.mapper';
import { normalizeAuthType } from '../domain/catalog-auth';
import { groupActiveConnectionsByApp, isDeactivatedConnection } from '../domain/connection';
import { computeDagLayout } from '../domain/dag/compute-dag-layout';
import {
  AuthType,
  ConnectionHandshakeStatus,
  ConnectionStatus,
  ConnectorDirection,
  ConnectorPropertyType,
  ConnectorRuntimeArchitecture,
  IP_PRODUCT_THEME_TOKEN,
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
import { clampSimulatorRecordsPerPull, extractSimulatorSandboxId } from '../domain/simulator';
import { buildRegisterStitchInput } from '../domain/stitch-registration';
import type { IpTrace } from '../domain/trace';
import {
  isAuthTypeValue,
  isReplayStageValue,
  isTransformationModeValue,
} from '../domain/type-guards';

describe('IP Domain: computeDagLayout', () => {
  it('assigns topological ranks with deterministic coordinates for multi-branch Stitch DAGs', () => {
    const layout = computeDagLayout([
      {
        nodeKey: 'query_source_replica',
        kind: 'TASK',
        stepType: 'query_replica',
        parents: [],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'ip.default',
      },
      {
        nodeKey: 'await_external_approval',
        kind: 'WAIT_FOR_EVENT',
        stepType: 'wait_signal',
        parents: ['query_source_replica'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: 'canonical.approval.granted',
        queueName: 'ip.default',
      },
      {
        nodeKey: 'push_sink_payload',
        kind: 'TASK',
        stepType: 'execute_http_action',
        parents: ['await_external_approval'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'IDEMPOTENT_EXTERNAL',
        waitEventKey: null,
        queueName: 'ip.delivery',
      },
      {
        nodeKey: 'notify_ops_on_failure',
        kind: 'TASK',
        stepType: 'emit_notification',
        parents: ['push_sink_payload'],
        edgeCondition: 'ON_FAILURE',
        effectPolicy: 'IDEMPOTENT_EXTERNAL',
        waitEventKey: null,
        queueName: 'ip.default',
      },
    ]);

    expect(layout.nodes).toHaveLength(4);
    expect(layout.edges).toHaveLength(3);

    const byKey = new Map(layout.nodes.map((node) => [node.node.nodeKey, node]));
    expect(byKey.get('query_source_replica')?.rank).toBe(0);
    expect(byKey.get('await_external_approval')?.rank).toBe(1);
    expect(byKey.get('push_sink_payload')?.rank).toBe(2);
    expect(byKey.get('notify_ops_on_failure')?.rank).toBe(3);
    expect(layout.width).toBeGreaterThan(800);
    expect(layout.height).toBeGreaterThan(140);
  });

  it('breaks cycles safely without hanging on malformed graph metadata', () => {
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

describe('IP Domain: Replay Eligibility', () => {
  const sampleFailedTrace: IpTrace = {
    traceId: 'ip_trc_101',
    tenantId: 'ten_01',
    correlationId: 'REC-700',
    originalTraceId: 'ip_trc_100',
    parentTraceId: 'ip_trc_100',
    replayCount: 1,
    status: 'FAILED',
    inboundRecord: {
      id: 'inb_01',
      tenantId: 'ten_01',
      traceId: 'ip_trc_101',
      correlationId: 'REC-700',
      parentTraceId: 'ip_trc_100',
      originalTraceId: 'ip_trc_100',
      replayCount: 1,
      connectionId: 'conn_acme',
      appId: 'acme_source',
      streamName: 'records_alpha',
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
        correlationId: 'REC-700',
        parentTraceId: 'ip_trc_100',
        originalTraceId: 'ip_trc_100',
        replayCount: 1,
        connectionId: 'conn_acme',
        stream: 'records_alpha',
        recordKey: 'REC-700',
        primaryKeyValues: ['REC-700'],
        cursorValue: '2026-10-29T08:00:00Z',
        cursorKind: 'TIMESTAMP',
        data: { record_id: 'REC-700', value_num: 42.5 },
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
        correlationId: 'REC-700',
        parentTraceId: 'ip_trc_100',
        originalTraceId: 'ip_trc_100',
        replayCount: 1,
        connectionId: 'conn_acme',
        canonicalType: 'canonical.record_alpha.v1',
        sourceId: 'REC-700',
        canonicalData: {
          external_serial_number: 'REC-700',
          metric_value: '42.5',
          extensions: { revision: '4.2' },
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
        correlationId: 'REC-700',
        parentTraceId: 'ip_trc_100',
        originalTraceId: 'ip_trc_100',
        replayCount: 1,
        entityDomain: 'domain.record_alpha',
        canonicalId: 'can_rec_700',
        sourceConnectionId: 'conn_acme',
        sourceEntityId: 'REC-700',
        destConnectionId: 'conn_globex',
        destEntityId: null,
        createdAt: '2026-10-29T08:00:01Z',
      },
    ],
    outboundRecords: [
      {
        id: 'out_01',
        tenantId: 'ten_01',
        traceId: 'ip_trc_101',
        correlationId: 'REC-700',
        parentTraceId: 'ip_trc_100',
        originalTraceId: 'ip_trc_100',
        replayCount: 1,
        connectionId: 'conn_globex',
        appId: 'globex_dest',
        streamName: 'canonical_sink',
        operation: 'UPSERT',
        idempotencyKey: 'idem_01',
        externalRecordId: null,
        targetUrl: 'https://globex.example.com/api/records',
        httpMethod: 'POST',
        requestHeaders: { authorization: '[REDACTED]' },
        requestBody: { record_id: 'REC-700', value_num: '42.5' },
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

  it('derives eligible deterministic replay stages with recommended failure target', () => {
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

  it('computes 5-layer waterfall posture while flagging unhydrated S3 payloads', () => {
    const summary = computePipelineWaterfallSummary(sampleFailedTrace);
    expect(summary.hasUnhydratedS3Payloads).toBe(true);
    const byLayer = new Map(summary.layers.map((layer) => [layer.layer, layer]));
    expect(byLayer.get(PipelineLayer.L1_INGEST)?.posture).toBe(StagePosture.HEALTHY);
    expect(byLayer.get(PipelineLayer.L2_REPLICA)?.posture).toBe(StagePosture.HEALTHY);
    expect(byLayer.get(PipelineLayer.L3_NORMALIZE)?.posture).toBe(StagePosture.HEALTHY);
    expect(byLayer.get(PipelineLayer.L5_DELIVER)?.posture).toBe(StagePosture.CRITICAL);
  });

  it('extracts modifiable payload seeds per eligible replay stage', () => {
    expect(extractModifiablePayloadSeed(sampleFailedTrace, ReplayStage.RETRY_INGEST)).toEqual({});
    expect(extractModifiablePayloadSeed(sampleFailedTrace, ReplayStage.RETRY_STITCH)).toMatchObject(
      {
        external_serial_number: 'REC-700',
      },
    );
  });

  it('returns empty eligibility for traces without persisted stage records', () => {
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
  });

  it('recommends normalization replay when normalization rejections exist', () => {
    const normRejectedTrace: IpTrace = {
      ...sampleFailedTrace,
      outboundRecords: [],
      normalizationRejections: [
        {
          id: 'nrej_1',
          tenantId: 'ten_01',
          traceId: 'ip_trc_101',
          correlationId: 'REC-700',
          replicaRecordId: 'rep_01',
          stream: 'records_alpha',
          transformationId: 'acme.v1',
          transformationVersion: 1,
          reasonCode: 'SCHEMA_INVALID',
          fieldPath: '$.value_num',
          detail: 'Negative value',
          createdAt: '2026-10-29T08:00:01Z',
        },
      ],
      traceEvents: [
        {
          id: 'ev_1',
          tenantId: 'ten_01',
          traceId: 'ip_trc_101',
          correlationId: 'REC-700',
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
  });

  it('recommends ingest replay when replica rejections exist', () => {
    const baseInbound = sampleFailedTrace.inboundRecord!;
    const baseOutbound = sampleFailedTrace.outboundRecords[0]!;
    const repRejectedTrace: IpTrace = {
      ...sampleFailedTrace,
      inboundRecord: {
        ...baseInbound,
        requestBody: { raw: 1 },
        requestS3Key: null,
      },
      replicaRecords: [],
      normalizedRecords: [],
      normalizationRejections: [],
      entityMappings: [],
      traceEvents: [],
      replicaRejections: [
        {
          id: 'rrej_1',
          tenantId: 'ten_01',
          traceId: 'ip_trc_101',
          connectionId: 'conn_acme',
          stream: 'records_alpha',
          inboundRecordId: 'inb_01',
          recordIndex: 0,
          reason: 'MISSING_PK',
          detail: 'record_id missing',
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

describe('IP Domain: Type Guards', () => {
  it('validates domain enum tokens without unsafe type casts', () => {
    expect(IP_PRODUCT_THEME_TOKEN).toBe('ip');
    expect(ConnectorDirection.BIDIRECTIONAL).toBe('BIDIRECTIONAL');
    expect(ConnectorDirection.SOURCE).toBe('SOURCE');
    expect(ConnectorDirection.DESTINATION).toBe('DESTINATION');
    expect(ConnectionHandshakeStatus.VERIFIED).toBe('VERIFIED');
    expect(ConnectionHandshakeStatus.AUTH_FAILED).toBe('AUTH_FAILED');
    expect(ReplayDispatchStatus.QUEUED).toBe('QUEUED');
    expect(ReplayDispatchStatus.COMPLETED).toBe('COMPLETED');
    expect(ReplayDispatchStatus.PARTIAL).toBe('PARTIAL');

    expect(ConnectionStatus.DEACTIVATED).toBe('DEACTIVATED');
    expect(PipelineLayer.L5_DELIVER).toBe('L5_DELIVER');
    expect(ConnectorRuntimeArchitecture.DECLARATIVE_HTTP).toBe('DECLARATIVE_HTTP');

    expect(normalizeConnectorPropertyType('oauth2')).toBe(ConnectorPropertyType.OAUTH);
    expect(normalizeConnectorPropertyType('OAUTH2')).toBe(ConnectorPropertyType.OAUTH);
    expect(normalizeConnectorPropertyType('oauth')).toBe(ConnectorPropertyType.OAUTH);
    expect(normalizeConnectorPropertyType('SECRET_TEXT')).toBe(ConnectorPropertyType.SECRET_TEXT);
    expect(normalizeConnectorPropertyType('SHORT_TEXT')).toBe(ConnectorPropertyType.SHORT_TEXT);
    expect(normalizeConnectorPropertyType('NUMBER')).toBe(ConnectorPropertyType.NUMBER);
    expect(normalizeConnectorPropertyType('BOOLEAN')).toBe(ConnectorPropertyType.BOOLEAN);
    expect(normalizeConnectorPropertyType('DROPDOWN')).toBe(ConnectorPropertyType.DROPDOWN);

    expect(isAuthTypeValue(AuthType.OAUTH2)).toBe(true);
    expect(isAuthTypeValue('CUSTOM_UNKNOWN')).toBe(false);
    expect(normalizeAuthType(AuthType.BEARER)).toBe(AuthType.BEARER);
    expect(normalizeAuthType('UNRECOGNIZED')).toBe(null);

    expect(isReplayStageValue(ReplayStage.RETRY_DELIVER)).toBe(true);
    expect(isReplayStageValue('INVALID_STAGE')).toBe(false);

    expect(isTransformationModeValue(TransformationMode.SHADOW)).toBe(true);
    expect(isTransformationModeValue('DRAFT')).toBe(false);
  });

  it('parses plain JSON objects while rejecting non-object JSON values', () => {
    expect(isPlainJsonRecord({ record_id: 'REC-700' })).toBe(true);
    expect(isPlainJsonRecord(null)).toBe(false);
    expect(isPlainJsonRecord(['a'])).toBe(false);
    expect(isPlainJsonRecord('str')).toBe(false);

    const valid = parseJsonObject('{"record_id":"REC-700","value_num":42.5}');
    expect(valid).toEqual({ ok: true, value: { record_id: 'REC-700', value_num: 42.5 } });

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

  it('normalizes RegisterStitchInput for trigger versus wait-condition bindings', () => {
    expect(
      buildRegisterStitchInput({
        workflowId: '  ',
        workflowVersion: 1,
        canonicalEventType: 'canonical.record_alpha.v1',
        isTrigger: true,
        conditionKey: '',
        idempotencyField: 'source_id',
        concurrencyField: '',
      }),
    ).toBeNull();

    const triggerInput = buildRegisterStitchInput({
      workflowId: 'workflow.sync_alpha_to_sink',
      workflowVersion: 2,
      canonicalEventType: ' canonical.record_alpha.v1 ',
      isTrigger: true,
      conditionKey: 'ignored_when_trigger',
      idempotencyField: ' source_id ',
      concurrencyField: '   ',
    });
    expect(triggerInput).toEqual({
      workflowId: 'workflow.sync_alpha_to_sink',
      workflowVersion: 2,
      canonicalEventType: 'canonical.record_alpha.v1',
      isTrigger: true,
      conditionEventKey: null,
      idempotencyKeyField: 'source_id',
      concurrencyKeyField: null,
      isActive: true,
    });

    const signalInput = buildRegisterStitchInput({
      workflowId: 'workflow.sync_alpha_to_sink',
      workflowVersion: 1,
      canonicalEventType: 'canonical.approval.granted',
      isTrigger: false,
      conditionKey: ' approval_gate ',
      idempotencyField: 'source_id',
      concurrencyField: ' record_id ',
    });
    expect(signalInput?.conditionEventKey).toBe('approval_gate');
    expect(signalInput?.concurrencyKeyField).toBe('record_id');
  });

  it('groups non-deactivated connections per appId', () => {
    const base = {
      id: 'conn_1',
      tenantId: 'ten_1',
      appId: 'stripe',
      name: 'Stripe Prod',
      authType: AuthType.API_KEY,
      publicConfig: {},
      status: ConnectionStatus.ACTIVE,
      connectionFingerprint: 'fp_1',
      tokenExpiresAt: null,
      lastRefreshedAt: null,
      lastErrorCode: null,
      lastErrorMessage: null,
      createdAt: '2026-10-30T00:00:00Z',
      updatedAt: '2026-10-30T00:00:00Z',
      deactivatedAt: null,
    } as const;

    const deactivated = {
      ...base,
      id: 'conn_2',
      status: ConnectionStatus.DEACTIVATED,
      deactivatedAt: '2026-10-31T00:00:00Z',
    };
    const expired = {
      ...base,
      id: 'conn_3',
      appId: 'hubspot',
      status: ConnectionStatus.AUTH_EXPIRED,
    };

    expect(isDeactivatedConnection(base)).toBe(false);
    expect(isDeactivatedConnection(deactivated)).toBe(true);

    const grouped = groupActiveConnectionsByApp([base, deactivated, expired]);
    expect(grouped.get('stripe')?.map((c) => c.id)).toEqual(['conn_1']);
    expect(grouped.get('hubspot')?.map((c) => c.id)).toEqual(['conn_3']);
  });

  it('clamps simulator recordsPerPull within configured bounds', () => {
    expect(clampSimulatorRecordsPerPull('0')).toBe(1);
    expect(clampSimulatorRecordsPerPull('99999')).toBe(5_000);
    expect(clampSimulatorRecordsPerPull('not-a-number')).toBe(25);
    expect(clampSimulatorRecordsPerPull('120')).toBe(120);
  });

  it('extracts trimmed simulator sandboxId from connection publicConfig', () => {
    expect(extractSimulatorSandboxId({ sandbox_id: '  sbx_00112233445566778899aabb  ' })).toBe(
      'sbx_00112233445566778899aabb',
    );
    expect(extractSimulatorSandboxId({ sandbox_id: '   ' })).toBeNull();
    expect(extractSimulatorSandboxId({ sandbox_id: 42 })).toBeNull();
    expect(extractSimulatorSandboxId({ seed: 42 })).toBeNull();
    expect(extractSimulatorSandboxId(null)).toBeNull();
    expect(extractSimulatorSandboxId(undefined)).toBeNull();
  });
});
