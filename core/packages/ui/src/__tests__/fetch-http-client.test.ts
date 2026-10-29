import { describe, expect, it } from 'vitest';
import { FetchHttpClientAdapter } from '../network/fetch-http-client';
import { ApiErrorCode, ApiProblemError, unwrapOrThrow } from '../network/ports';

interface RecordedFetchCall {
  readonly url: string;
  readonly init: RequestInit | undefined;
}

function resolveInputUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') {
    return input;
  }
  if (input instanceof URL) {
    return input.toString();
  }
  return input.url;
}

function createQueuedFetch(handlers: ReadonlyArray<() => Promise<Response>>): {
  readonly fetchImpl: typeof fetch;
  readonly calls: RecordedFetchCall[];
} {
  const calls: RecordedFetchCall[] = [];
  let cursor = 0;

  const fetchImpl: typeof fetch = async (input, init) => {
    calls.push({ url: resolveInputUrl(input), init });
    const handler = handlers[cursor] ?? handlers[handlers.length - 1];
    cursor += 1;
    if (!handler) {
      throw new Error('No queued Response configured for FakeFetch');
    }
    return handler();
  };

  return { fetchImpl, calls };
}

describe('FetchHttpClientAdapter', () => {
  it('executes GET with filtered query params and dynamic Bearer token without Idempotency-Key', async () => {
    const transport = createQueuedFetch([
      async () =>
        new Response(JSON.stringify({ items: ['mtr-700'] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    ]);

    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local/api/v1/',
      getToken: () => 'tok_live_123',
      fetchImpl: transport.fetchImpl,
    });

    const result = await client.get<{ items: string[] }>('/ip/catalog/apps', {
      params: { category: 'energy', search: undefined, limit: 25 },
    });

    expect(result).toEqual({ ok: true, value: { items: ['mtr-700'] } });
    expect(transport.calls).toHaveLength(1);

    const firstCall = transport.calls[0];
    expect(firstCall?.url).toBe(
      'https://api.soopa.local/api/v1/ip/catalog/apps?category=energy&limit=25',
    );
    const headers = new Headers(firstCall?.init?.headers);
    expect(headers.get('Authorization')).toBe('Bearer tok_live_123');
    expect(headers.get('Idempotency-Key')).toBeNull();
  });

  it('injects automatic UUID Idempotency-Key on POST/PUT/PATCH/DELETE and preserves caller override', async () => {
    const transport = createQueuedFetch([
      async () => new Response(JSON.stringify({ accepted: true }), { status: 202 }),
      async () => new Response(JSON.stringify({ accepted: true }), { status: 202 }),
    ]);

    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local/api/v1',
      fetchImpl: transport.fetchImpl,
    });

    await client.post('/ip/connections', { app_id: 'itron' });
    await client.post(
      '/ip/connections',
      { app_id: 'itron' },
      { idempotencyKey: 'idem_explicit_key_001' },
    );

    const firstHeaders = new Headers(transport.calls[0]?.init?.headers);
    const secondHeaders = new Headers(transport.calls[1]?.init?.headers);

    expect(firstHeaders.get('Idempotency-Key')).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
    );
    expect(secondHeaders.get('Idempotency-Key')).toBe('idem_explicit_key_001');
  });

  it('handles 204 No Content cleanly without JSON parsing errors', async () => {
    const transport = createQueuedFetch([async () => new Response(null, { status: 204 })]);
    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local/api/v1',
      fetchImpl: transport.fetchImpl,
    });

    const result = await client.delete<void>('/ip/connections/ip_conn_123');
    expect(result).toEqual({ ok: true, value: undefined });
  });

  it('returns structured Result error (without throwing) on 409, 422, and 429 Retry-After', async () => {
    const transport = createQueuedFetch([
      async () =>
        new Response(
          JSON.stringify({
            error_code: 'DUPLICATE_FINGERPRINT',
            message: 'Connection with identical credentials already exists',
          }),
          { status: 409, headers: { 'X-Correlation-ID': 'corr_991' } },
        ),
      async () =>
        new Response(
          JSON.stringify({
            detail: [{ loc: ['body', 'modified_payload'], msg: 'Object required' }],
          }),
          { status: 422 },
        ),
      async () =>
        new Response(JSON.stringify({ detail: 'Rate limit exceeded' }), {
          status: 429,
          headers: { 'Retry-After': '15' },
        }),
    ]);

    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local/api/v1',
      fetchImpl: transport.fetchImpl,
    });

    const conflict = await client.post('/ip/connections', {});
    expect(conflict).toEqual({
      ok: false,
      error: {
        code: ApiErrorCode.CONFLICT,
        status: 409,
        serverCode: 'DUPLICATE_FINGERPRINT',
        message: 'Connection with identical credentials already exists',
        correlationId: 'corr_991',
        retryAfterSeconds: undefined,
        fieldErrors: undefined,
      },
    });

    const validation = await client.post('/ip/transactions/trc_1/modify-and-replay', {});
    expect(validation.ok).toBe(false);
    if (!validation.ok) {
      expect(validation.error.code).toBe(ApiErrorCode.VALIDATION_ERROR);
      expect(validation.error.status).toBe(422);
      expect(validation.error.fieldErrors).toEqual({
        modified_payload: 'Object required',
      });
    }

    const rateLimited = await client.post('/ip/connections/check', {});
    expect(rateLimited.ok).toBe(false);
    if (!rateLimited.ok) {
      expect(rateLimited.error.code).toBe(ApiErrorCode.RATE_LIMITED);
      expect(rateLimited.error.retryAfterSeconds).toBe(15);
    }
  });

  it('maps caller AbortSignal cancellation to NETWORK_ABORTED Result without throwing', async () => {
    const abortController = new AbortController();
    abortController.abort();

    const transport = createQueuedFetch([
      async () => {
        throw new DOMException('The operation was aborted.', 'AbortError');
      },
    ]);

    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local/api/v1',
      fetchImpl: transport.fetchImpl,
    });

    const result = await client.get('/ip/transactions/search', {
      signal: abortController.signal,
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe(ApiErrorCode.NETWORK_ABORTED);
      expect(result.error.status).toBe(0);
    }
  });

  it('supports explicit opt-in unwrapOrThrow for legacy callers requiring thrown ApiProblemError', () => {
    expect(unwrapOrThrow({ ok: true, value: 42 })).toBe(42);
    expect(() =>
      unwrapOrThrow({
        ok: false,
        error: {
          code: ApiErrorCode.NOT_FOUND,
          status: 404,
          message: 'Trace not found',
        },
      }),
    ).toThrow(ApiProblemError);
  });
});
