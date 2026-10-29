import { describe, expect, it } from 'vitest';
import { FetchHttpClientAdapter } from '../network/fetch-http-client';
import { ApiErrorCode } from '../network/ports';
import {
  ConsoleJsonLogSink,
  LogLevel,
  StructuredJsonLoggerAdapter,
  type StructuredLogEntry,
} from '../observability';
import { RecordingLoggerFake } from '../testing';

function createQueuedFetch(responses: ReadonlyArray<() => Promise<Response>>): typeof fetch {
  let index = 0;
  return async () => {
    const next = responses[index];
    index += 1;
    if (!next) {
      throw new Error('Unexpected fetch call');
    }
    return next();
  };
}

describe('StructuredJsonLoggerAdapter & FetchHttpClientAdapter Telemetry', () => {
  it('binds immutable context attributes and emits structured JSON payloads without string interpolation', () => {
    const captured: StructuredLogEntry[] = [];
    const rootLogger = new StructuredJsonLoggerAdapter({
      sink: {
        emit: (entry) => {
          captured.push(entry);
        },
      },
      clock: () => '2026-10-29T09:00:00.000Z',
    });

    const tenantLogger = rootLogger.bind({ product: 'ip', tenant_id: 'ten_solar_01' });
    tenantLogger.info('ip_workspace.mounted', { route: '/tenant/ip/traces' });
    tenantLogger.error('ip_replay.failed', { trace_id: 'trc_99', status: 422 });

    expect(captured).toEqual([
      {
        timestamp: '2026-10-29T09:00:00.000Z',
        level: LogLevel.INFO,
        event: 'ip_workspace.mounted',
        attributes: {
          product: 'ip',
          tenant_id: 'ten_solar_01',
          route: '/tenant/ip/traces',
        },
      },
      {
        timestamp: '2026-10-29T09:00:00.000Z',
        level: LogLevel.ERROR,
        event: 'ip_replay.failed',
        attributes: {
          product: 'ip',
          tenant_id: 'ten_solar_01',
          trace_id: 'trc_99',
          status: 422,
        },
      },
    ]);
  });

  it('logs INFO on 2xx and ERROR on 4xx/5xx/SCHEMA_DRIFT with Retry-After and correlation_id', async () => {
    const logger = new RecordingLoggerFake().bind({ tenant_id: 'ten_01' });
    const fakeFetch = createQueuedFetch([
      async () =>
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      async () =>
        new Response(JSON.stringify({ detail: 'Rate limit exceeded' }), {
          status: 429,
          headers: { 'Retry-After': '30', 'X-Correlation-ID': 'corr_rate_01' },
        }),
      async () => new Response('<<<not-json>>>', { status: 200 }),
    ]);

    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local/api/v1',
      fetchImpl: fakeFetch,
      logger,
    });

    const okRes = await client.get('/ip/catalog/apps');
    expect(okRes.ok).toBe(true);

    const rateRes = await client.post('/ip/connections/check', {});
    expect(rateRes.ok).toBe(false);

    const driftRes = await client.get('/ip/stitches/runs');
    expect(driftRes.ok).toBe(false);

    expect(logger.entries).toHaveLength(3);
    const [first, second, third] = logger.entries;
    expect(first).toBeDefined();
    expect(second).toBeDefined();
    expect(third).toBeDefined();

    if (first && second && third) {
      expect(first.level).toBe(LogLevel.INFO);
      expect(first.event).toBe('http_request.completed');
      expect(first.attributes.status).toBe(200);
      expect(first.attributes.tenant_id).toBe('ten_01');

      expect(second.level).toBe(LogLevel.ERROR);
      expect(second.event).toBe('http_request.failed');
      expect(second.attributes.error_code).toBe(ApiErrorCode.RATE_LIMITED);
      expect(second.attributes.retry_after_seconds).toBe(30);
      expect(second.attributes.correlation_id).toBe('corr_rate_01');

      expect(third.level).toBe(LogLevel.ERROR);
      expect(third.event).toBe('http_request.failed');
      expect(third.attributes.error_code).toBe(ApiErrorCode.SCHEMA_DRIFT);
    }
  });

  it('logs WARN strictly on benign in-flight AbortSignal cancellation', async () => {
    const logger = new RecordingLoggerFake().bind({ tenant_id: 'ten_01' });
    const fakeFetch = createQueuedFetch([
      async () => {
        throw new DOMException('Aborted', 'AbortError');
      },
    ]);

    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local/api/v1',
      fetchImpl: fakeFetch,
      logger,
    });

    const abortRes = await client.get('/ip/transactions/search');
    expect(abortRes.ok).toBe(false);
    expect(logger.entries).toHaveLength(1);
    expect(logger.entries[0]?.level).toBe(LogLevel.WARN);
    expect(logger.entries[0]?.event).toBe('http_request.aborted');
    expect(logger.entries[0]?.attributes.error_code).toBe(ApiErrorCode.NETWORK_ABORTED);
  });

  it('routes DEBUG, INFO, WARN, ERROR through ConsoleJsonLogSink and exercises PUT/PATCH/DELETE verbs', async () => {
    const bucket: Record<string, string[]> = { debug: [], info: [], warn: [], error: [] };
    const sink = new ConsoleJsonLogSink({
      debug: (msg) => bucket.debug?.push(msg),
      info: (msg) => bucket.info?.push(msg),
      warn: (msg) => bucket.warn?.push(msg),
      error: (msg) => bucket.error?.push(msg),
    });
    const logger = new StructuredJsonLoggerAdapter({
      sink,
      bindings: { product: 'ip', ignored: undefined },
    });

    logger.debug('cache.hit', { key: 'k1', skip: undefined });
    logger.info('sync.started', { stream: 'meters' });
    logger.warn('sync.retrying', { attempt: 2 });
    logger.error('sync.exhausted', { status: 503 });

    expect(bucket.debug).toHaveLength(1);
    expect(bucket.info).toHaveLength(1);
    expect(bucket.warn).toHaveLength(1);
    expect(bucket.error).toHaveLength(1);

    const fakeFetch = createQueuedFetch([
      async () =>
        new Response(JSON.stringify({ updated: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      async () =>
        new Response(JSON.stringify({ patched: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      async () => new Response(null, { status: 204 }),
    ]);

    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local/api/v1',
      fetchImpl: fakeFetch,
      getToken: () => 'jwt_123',
      logger,
    });

    expect((await client.put('/ip/transformations', { mode: 'ACTIVE' })).ok).toBe(true);
    expect((await client.patch('/ip/connections/conn_1', { name: 'New' })).ok).toBe(true);
    expect((await client.delete('/ip/connections/conn_1')).ok).toBe(true);
  });

  it('classifies NestJS array errors, structured detail objects, plain-text 502s, empty 200s, and non-Error throws', async () => {
    const fakeFetch = createQueuedFetch([
      async () =>
        new Response(JSON.stringify({ message: ['email must be valid'] }), { status: 400 }),
      async () =>
        new Response(
          JSON.stringify({ detail: { message: 'Quota reached', error_code: 'QUOTA_LIMIT' } }),
          { status: 403 },
        ),
      async () => new Response('<html>502 Bad Gateway</html>', { status: 502 }),
      async () => new Response('', { status: 200 }),
      async () => {
        throw new TypeError('Failed to fetch');
      },
    ]);

    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local/api/v1/',
      fetchImpl: fakeFetch,
    });

    const nestErr = await client.post('users', {});
    expect(!nestErr.ok && nestErr.error.message).toBe('email must be valid');

    const detailObjErr = await client.get('quotas', {
      params: { active: true, page: 1, empty: undefined },
    });
    expect(!detailObjErr.ok && detailObjErr.error.serverCode).toBe('QUOTA_LIMIT');

    const gatewayErr = await client.get('health');
    expect(!gatewayErr.ok && gatewayErr.error.code).toBe(ApiErrorCode.SERVER_ERROR);

    const emptyOk = await client.get('ping');
    expect(emptyOk.ok).toBe(true);

    const rawThrow = await client.get('crash');
    expect(!rawThrow.ok && rawThrow.error.code).toBe(ApiErrorCode.NETWORK_FAILURE);
  });
});
