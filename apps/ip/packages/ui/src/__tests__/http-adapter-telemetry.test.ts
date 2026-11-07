import { ApiErrorCode, FetchHttpClientAdapter } from '@soopa/ui';
import { describe, expect, it } from 'vitest';
import { HttpConnectionRepository } from '../adapters/http/repositories/http-connection.repository';
import { HttpStitchRepository } from '../adapters/http/repositories/http-stitch.repository';
import { HttpTraceRepository } from '../adapters/http/repositories/http-trace.repository';
import { HttpTransformationRepository } from '../adapters/http/repositories/http-transformation.repository';
import { AuthType } from '../domain/enums';

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
    matches: (url) => url.includes('/traces/search'),
    payload: [
      {
        trace_id: 'ip_trc_700',
        correlation_id: 'REC-700',
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
      message: 'Authenticated with Acme Gateway v2',
      error_code: null,
    },
  },
  {
    matches: (url) => url.endsWith('/transformations/preview'),
    payload: {
      transformation_id: 'acme.record_alpha.to_gem',
      transformation_version: 1,
      drafts: [
        {
          canonical_type: 'canonical.record_alpha.v1',
          source_id: 'REC-700',
          fields: { metric_value: '88.4' },
          extensions: { channel: 'A' },
          references: [],
        },
      ],
      rejections: [],
      shadow_transformation_version: 2,
      shadow_diffs: {
        'canonical.record_alpha.v1:REC-700': {
          active: { metric_value: '88.4' },
          shadow: { metric_value: '88.400', unit: 'COUNT' },
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
        workflow_id: 'workflow.sync_alpha_to_sink',
        workflow_version: 1,
        status: 'RUNNING',
        priority: 'HIGH',
        concurrency_key: 'REC-700',
        idempotency_key: 'idem_700',
        trace_id: 'ip_trc_700',
        correlation_id: 'REC-700',
        failure_code: null,
        failure_detail: null,
        created_at: '2026-10-29T08:10:00Z',
        started_at: '2026-10-29T08:10:01Z',
        finished_at: null,
        steps: [
          {
            step_run_id: 'stp_01',
            node_key: 'push_sink',
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

describe('IP HTTP Adapter Narrow Integration', () => {
  it('maps trace correlation search responses in HttpTraceRepository', async () => {
    const { client } = createRecordedTestClient();
    const traceRepo = new HttpTraceRepository(client);

    const searchRes = await traceRepo.searchByCorrelation('ten_01', 'REC-700', 25);
    expect(searchRes.ok).toBe(true);
    if (searchRes.ok) {
      expect(searchRes.value[0]).toMatchObject({ traceId: 'ip_trc_700', replayCount: 1 });
    }
  });

  it('attaches Idempotency-Key header during pre-flight check in HttpConnectionRepository', async () => {
    const { client, recordedHeaders } = createRecordedTestClient();
    const connRepo = new HttpConnectionRepository(client);

    const checkRes = await connRepo.checkConnection('ten_01', {
      appId: 'acme_source',
      authType: AuthType.OAUTH2,
      publicConfig: { base_url: 'https://api.acme.example.com' },
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

  it('maps transformation shadow preview with Idempotency-Key in HttpTransformationRepository', async () => {
    const { client, recordedHeaders } = createRecordedTestClient();
    const transformRepo = new HttpTransformationRepository(client);

    const previewRes = await transformRepo.previewTransformation('ten_01', {
      connectionId: 'conn_acme',
      stream: 'records_alpha',
      transformationId: 'acme.record_alpha.to_gem',
      transformationVersion: 1,
      recordKey: 'REC-700',
      samplePayload: { record_id: 'REC-700', value_num: 88.4 },
      shadowTransformationVersion: 2,
    });
    expect(previewRes.ok).toBe(true);
    if (previewRes.ok) {
      expect(previewRes.value.drafts).toHaveLength(1);
      expect(previewRes.value.shadowTransformationVersion).toBe(2);
    }

    const postCalls = recordedHeaders.filter((c) => c.method === 'POST');
    expect(postCalls).toHaveLength(1);
    expect(postCalls[0]?.idempotencyKey).toBeTruthy();
  });

  it('maps stitch step retry telemetry in HttpStitchRepository', async () => {
    const { client } = createRecordedTestClient();
    const stitchRepo = new HttpStitchRepository(client);

    const runsRes = await stitchRepo.listRuns('ten_01', { limit: 10 });
    expect(runsRes.ok).toBe(true);
    if (runsRes.ok) {
      expect(runsRes.value[0]?.steps[0]).toMatchObject({
        internalRetryCount: 1,
        appRetryCount: 0,
      });
    }
  });

  it('returns structured SCHEMA_DRIFT error instead of throwing on wire payload drift', async () => {
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
