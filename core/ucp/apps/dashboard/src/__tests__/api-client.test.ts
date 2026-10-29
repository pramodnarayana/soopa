import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { UcpApiClientProvider, useUcpApiClient } from '../contexts/UcpApiClientContext';
import {
  createScopedUcpApiClient,
  HttpMethod,
  isHttpMethodValue,
  parseHttpMethod,
} from '../lib/api-client';

describe('UCP Dashboard Scoped API Client & Context DI', () => {
  it('validates HTTP method strings via type guard without unsafe casts', () => {
    expect(isHttpMethodValue('GET')).toBe(true);
    expect(isHttpMethodValue('PATCH')).toBe(true);
    expect(isHttpMethodValue('TRACE_INVALID')).toBe(false);

    expect(parseHttpMethod('post')).toBe(HttpMethod.POST);
    expect(parseHttpMethod('DELETE')).toBe(HttpMethod.DELETE);
    expect(parseHttpMethod('UNKNOWN_VERB')).toBe(HttpMethod.GET);
    expect(parseHttpMethod(undefined)).toBe(HttpMethod.GET);
  });

  it('reuses a single FetchHttpClientAdapter instance while reading fresh OIDC tokens per request', async () => {
    let activeToken: string | null = 'tok_initial';
    const capturedCalls: Array<{
      readonly url: string;
      readonly method: string;
      readonly auth: string | null;
      readonly body: string | null;
    }> = [];

    const fetchImpl: typeof fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      const headers = new Headers(init?.headers);
      capturedCalls.push({
        url,
        method: init?.method ?? 'GET',
        auth: headers.get('Authorization'),
        body: typeof init?.body === 'string' ? init.body : null,
      });
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    const client = createScopedUcpApiClient({
      baseUrl: 'https://ucp.soopa.local/api/v1',
      getToken: () => activeToken,
      fetchImpl,
    });

    await client.get('/auth/me');
    activeToken = 'tok_rotated';
    await client.request('/tenants', {
      method: 'post',
      body: JSON.stringify({ name: 'Solar Grid' }),
    });

    expect(capturedCalls).toHaveLength(2);
    expect(capturedCalls[0]?.auth).toBe('Bearer tok_initial');
    expect(capturedCalls[1]?.auth).toBe('Bearer tok_rotated');
    expect(capturedCalls[1]?.method).toBe('POST');
    expect(capturedCalls[1]?.body).toBe('{"name":"Solar Grid"}');
  });

  it('provides scoped UcpApiClientPort via React Context and rejects orphan consumers', () => {
    function OrphanConsumer(): React.ReactElement {
      useUcpApiClient();
      return React.createElement('div');
    }

    expect(() => renderToStaticMarkup(React.createElement(OrphanConsumer))).toThrow(
      'useUcpApiClient must be used inside <UcpApiClientProvider>.',
    );

    let injected = false;
    function ValidConsumer(): React.ReactElement {
      const client = useUcpApiClient();
      injected = Boolean(client.httpClient);
      return React.createElement('span', null, 'mounted');
    }

    const html = renderToStaticMarkup(
      React.createElement(UcpApiClientProvider, {
        token: 'tok_ctx',
        children: React.createElement(ValidConsumer),
      }),
    );
    expect(injected).toBe(true);
    expect(html).toContain('mounted');
  });
});
