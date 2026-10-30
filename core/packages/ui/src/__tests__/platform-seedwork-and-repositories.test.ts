import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { CopyableIdPill } from '../components/observability/copyable-id-pill';
import {
  type ClipboardWriterPort,
  useClipboardCopy,
  writeTextSafely,
} from '../components/observability/use-clipboard-copy';
import * as productThemeModule from '../contexts/useProductTheme';
import { applyProductTheme, useProductTheme } from '../contexts/useProductTheme';
import { apiTokenKeys, useApiTokensQuery } from '../features/developers/api/apiTokenHooks';
import { HttpApiTokenRepository } from '../features/developers/api/apiTokenRepository';
import { HttpNotificationConfigRepository } from '../features/notifications/api/notificationConfigRepository';
import { HttpNotificationRepository } from '../features/notifications/api/notificationRepository';
import {
  notificationConfigKeys,
  usePreferences,
  useTemplates,
} from '../features/notifications/api/useNotificationConfig';
import { notificationKeys, useNotifications } from '../features/notifications/api/useNotifications';
import { useWebhooksQuery, webhookKeys } from '../features/webhooks/api/webhookHooks';
import { HttpWebhookRepository } from '../features/webhooks/api/webhookRepository';
import {
  ApiErrorCode,
  err,
  FetchHttpClientAdapter,
  ok,
  projectPlatformResultQuery,
  recordPlatformMutationOutcome,
} from '../network';
import { LogLevel } from '../observability';
import { RecordingLoggerFake } from '../testing';

interface CapturedRequest {
  readonly url: string;
  readonly method: string;
  readonly body: string | null;
}

function createRecordingFetch(
  responder: (req: CapturedRequest, index: number) => Response | Promise<Response>,
): {
  readonly fetchImpl: typeof fetch;
  readonly requests: CapturedRequest[];
} {
  const requests: CapturedRequest[] = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    const url =
      typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const method = init?.method ?? 'GET';
    const body = typeof init?.body === 'string' ? init.body : null;
    const captured: CapturedRequest = { url, method, body };
    requests.push(captured);
    return responder(captured, requests.length - 1);
  };
  return { fetchImpl, requests };
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('Platform UI Seedwork — Pure & Independent IoC Theme + Safe Clipboard', () => {
  it('keeps useProductTheme 100% domain-agnostic (zero bounded domain constants) and restores prior dataset state', () => {
    expect('ProductTheme' in productThemeModule).toBe(false);

    const root = { dataset: {} as { productTheme?: string } };
    const cleanupFirst = applyProductTheme(root, 'solar-ops');
    expect(root.dataset.productTheme).toBe('solar-ops');

    const cleanupSecond = applyProductTheme(root, 'partner-portal');
    expect(root.dataset.productTheme).toBe('partner-portal');

    const cleanupDefault = applyProductTheme(root, null);
    expect(root.dataset.productTheme).toBeUndefined();

    cleanupDefault();
    expect(root.dataset.productTheme).toBe('partner-portal');

    cleanupSecond();
    expect(root.dataset.productTheme).toBe('solar-ops');

    cleanupFirst();
    expect(root.dataset.productTheme).toBeUndefined();

    function ThemeProbe(): React.ReactElement {
      useProductTheme('custom-theme');
      return React.createElement('span', null, 'themed');
    }
    expect(renderToStaticMarkup(React.createElement(ThemeProbe))).toContain('themed');
  });

  it('handles missing clipboard and rejected writeText without throwing unhandled rejections', async () => {
    expect(await writeTextSafely('trc_01', null)).toBe(false);
    expect(await writeTextSafely('trc_01', undefined)).toBe(false);

    const written: string[] = [];
    const okClipboard: ClipboardWriterPort = {
      writeText: async (text: string) => {
        written.push(text);
      },
    };
    expect(await writeTextSafely('trc_ok_99', okClipboard)).toBe(true);
    expect(written).toEqual(['trc_ok_99']);

    const deniedClipboard: ClipboardWriterPort = {
      writeText: async () => {
        throw new DOMException('Write permission denied', 'NotAllowedError');
      },
    };
    expect(await writeTextSafely('trc_denied', deniedClipboard)).toBe(false);

    function ClipboardProbe(): React.ReactElement {
      const { copied } = useClipboardCopy(1_200, okClipboard);
      return React.createElement(
        'div',
        null,
        copied ? 'copied' : 'idle',
        React.createElement(CopyableIdPill, {
          value: 'trc_abcdef1234567890',
          prefixLabel: 'Trace',
          truncateLength: 10,
        }),
      );
    }

    const html = renderToStaticMarkup(React.createElement(ClipboardProbe));
    expect(html).toContain('idle');
    expect(html).toContain('Trace:');
  });
});

describe('Platform UI Adapters — HttpClientPort DI, Result<T, ApiProblem> & Structured Telemetry', () => {
  it('executes HttpApiTokenRepository via injected HttpClientPort without throwing on 4xx/5xx', async () => {
    const logger = new RecordingLoggerFake().bind({ feature: 'api_tokens' });
    const { fetchImpl, requests } = createRecordingFetch((_req, idx) => {
      if (idx === 0) {
        return jsonResponse([
          {
            id: 'tok_01',
            name: 'ERP Prod',
            client_id: 'cli_01',
            active: true,
            created_at: '2026-10-29T00:00:00Z',
            last_used_at: null,
          },
        ]);
      }
      if (idx === 1) {
        return jsonResponse({
          id: 'tok_02',
          name: 'CRM Sync',
          client_id: 'cli_02',
          token: 'cli_02.sec_xyz',
          created_at: '2026-10-29T01:00:00Z',
        });
      }
      if (idx === 2) {
        return new Response(null, { status: 204 });
      }
      if (idx === 3) {
        return new Response(null, { status: 204 });
      }
      return jsonResponse({ detail: 'Forbidden token scope' }, 403);
    });

    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local/api/v1',
      fetchImpl,
      logger,
    });
    const repo = new HttpApiTokenRepository(client, 'ten_a1b2c3');

    const listRes = await repo.getAll();
    expect(listRes.ok && listRes.value).toHaveLength(1);
    expect(requests[0]?.url).toBe('https://api.soopa.local/api/v1/tenants/ten_a1b2c3/tokens');

    const createRes = await repo.create({ name: 'CRM Sync' });
    expect(createRes.ok && createRes.value.client_id).toBe('cli_02');

    const updateRes = await repo.update('tok_01', { active: false });
    expect(updateRes.ok).toBe(true);
    expect(requests[2]?.url).toBe(
      'https://api.soopa.local/api/v1/tenants/ten_a1b2c3/tokens/tok_01',
    );
    expect(requests[2]?.method).toBe('PATCH');

    const deleteRes = await repo.delete('tok_01');
    expect(deleteRes.ok).toBe(true);
    expect(requests[3]?.method).toBe('DELETE');

    const forbiddenRes = await repo.getAll();
    expect(forbiddenRes.ok).toBe(false);
    if (!forbiddenRes.ok) {
      expect(forbiddenRes.error.code).toBe(ApiErrorCode.FORBIDDEN);
      expect(forbiddenRes.error.message).toBe('Forbidden token scope');
    }
    expect(logger.entries.some((e) => e.level === LogLevel.ERROR)).toBe(true);
  });

  it('executes HttpWebhookRepository via injected HttpClientPort without throwing on validation errors', async () => {
    const logger = new RecordingLoggerFake().bind({ feature: 'webhooks' });
    const { fetchImpl, requests } = createRecordingFetch((_req, idx) => {
      if (idx === 0) {
        return jsonResponse([
          {
            id: 'wh_01',
            tenant_id: 'ten_wh',
            name: 'Inbound Hook',
            url: 'https://acme.example/hook',
            active: true,
            created_at: '2026-10-29T00:00:00Z',
            updated_at: '2026-10-29T00:00:00Z',
          },
        ]);
      }
      if (idx === 1) {
        return jsonResponse({ detail: 'URL must use HTTPS' }, 422);
      }
      if (idx === 2) {
        return jsonResponse({
          id: 'wh_01',
          tenant_id: 'ten_wh',
          name: 'Updated Hook',
          url: 'https://acme.example/hook',
          active: false,
          created_at: '2026-10-29T00:00:00Z',
          updated_at: '2026-10-29T02:00:00Z',
        });
      }
      return new Response(null, { status: 204 });
    });

    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local/api/v1',
      fetchImpl,
      logger,
    });
    const repo = new HttpWebhookRepository(client, 'ten_wh');

    const allRes = await repo.getAll();
    expect(allRes.ok && allRes.value[0]?.id).toBe('wh_01');
    expect(requests[0]?.url).toBe('https://api.soopa.local/api/v1/tenants/ten_wh/webhooks');

    const badCreate = await repo.create({ name: 'Bad', url: 'http://insecure.local' });
    expect(badCreate.ok).toBe(false);
    if (!badCreate.ok) {
      expect(badCreate.error.code).toBe(ApiErrorCode.VALIDATION_ERROR);
    }

    const updated = await repo.update('wh_01', { active: false });
    expect(updated.ok && updated.value.active).toBe(false);

    const deleted = await repo.delete('wh_01');
    expect(deleted.ok).toBe(true);
  });

  it('executes HttpNotificationRepository and HttpNotificationConfigRepository with structured Result returns', async () => {
    const logger = new RecordingLoggerFake().bind({ feature: 'notifications' });
    const { fetchImpl, requests } = createRecordingFetch((req) => {
      if (req.url.endsWith('/in-app') && req.method === 'GET') {
        return jsonResponse([
          {
            id: 'ntf_1',
            title: 'Sync failed',
            body: 'Check credentials',
            severity: 'high',
            is_read: false,
            created_at: '2026-10-29T00:00:00Z',
          },
        ]);
      }
      if (req.url.endsWith('/in-app/ntf_1/read') && req.method === 'PUT') {
        return new Response(null, { status: 204 });
      }
      if (req.url.endsWith('/preferences') && req.method === 'GET') {
        return jsonResponse([
          { id: 'pref_1', tenant_id: 'ten_ntf', event_type: 'sync.failed', channels: ['IN_APP'] },
        ]);
      }
      if (req.url.includes('/preferences/sync.failed') && req.method === 'PUT') {
        return jsonResponse({
          id: 'pref_1',
          tenant_id: 'ten_ntf',
          event_type: 'sync.failed',
          channels: ['IN_APP', 'EMAIL'],
        });
      }
      if (req.url.includes('/preferences/sync.failed') && req.method === 'DELETE') {
        return new Response(null, { status: 204 });
      }
      if (req.url.endsWith('/templates') && req.method === 'GET') {
        return jsonResponse([
          {
            id: 'tpl_1',
            tenant_id: 'ten_ntf',
            name: 'Default Alert',
            event_type: 'sync.failed',
            channel: 'IN_APP',
            subject_template: null,
            body_template: 'Hello {{ user_name }}',
            is_active: true,
          },
        ]);
      }
      if (req.url.endsWith('/templates') && req.method === 'PUT') {
        return jsonResponse({
          id: 'tpl_2',
          tenant_id: 'ten_ntf',
          name: 'Email Alert',
          event_type: 'sync.failed',
          channel: 'EMAIL',
          subject_template: 'Alert',
          body_template: 'Body',
          is_active: true,
        });
      }
      if (req.url.endsWith('/templates/tpl_1') && req.method === 'DELETE') {
        return new Response(null, { status: 204 });
      }
      if (req.url.endsWith('/templates/preview') && req.method === 'POST') {
        return jsonResponse({ rendered_subject: 'Subj', rendered_body: 'Hello Alice' });
      }
      return jsonResponse({ detail: 'Unexpected route' }, 500);
    });

    const client = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local/api/v1/notifications',
      fetchImpl,
      logger,
    });

    const inboxRepo = new HttpNotificationRepository(client, 'ten_ntf', 'usr_01');
    const inboxRes = await inboxRepo.listInApp();
    expect(inboxRes.ok && inboxRes.value).toHaveLength(1);
    expect((await inboxRepo.markAsRead('ntf_1')).ok).toBe(true);

    const cfgRepo = new HttpNotificationConfigRepository(client, 'ten_ntf');
    expect((await cfgRepo.listPreferences()).ok).toBe(true);
    expect((await cfgRepo.upsertPreference('sync.failed', ['IN_APP', 'EMAIL'])).ok).toBe(true);
    expect((await cfgRepo.deletePreference('sync.failed')).ok).toBe(true);
    expect((await cfgRepo.listTemplates()).ok).toBe(true);
    expect(
      (
        await cfgRepo.upsertTemplate({
          name: 'Email Alert',
          event_type: 'sync.failed',
          channel: 'EMAIL',
          subject_template: 'Alert',
          body_template: 'Body',
          is_active: true,
        })
      ).ok,
    ).toBe(true);
    expect((await cfgRepo.deleteTemplate('tpl_1')).ok).toBe(true);
    const previewRes = await cfgRepo.previewTemplate({ body_template: 'Hi' });
    expect(previewRes.ok && previewRes.value.rendered_body).toBe('Hello Alice');
    expect(requests).toHaveLength(9);
  });

  it('projects Result<T, ApiProblem> queries and logs mutation outcomes without throwing', () => {
    const logger = new RecordingLoggerFake();
    const okOutcome = recordPlatformMutationOutcome(logger, 'webhook.created', ok({ id: 'wh_1' }), {
      tenant_id: 'ten_1',
    });
    expect(okOutcome).toBe(true);

    const problem = {
      code: ApiErrorCode.SERVER_ERROR,
      message: 'Gateway timeout',
      status: 504,
      retryable: true,
    } as const;
    const errOutcome = recordPlatformMutationOutcome(logger, 'webhook.created', err(problem), {
      tenant_id: 'ten_1',
    });
    expect(errOutcome).toBe(false);
    expect(logger.entries[0]?.level).toBe(LogLevel.INFO);
    expect(logger.entries[1]?.level).toBe(LogLevel.ERROR);
    expect(logger.entries[1]?.attributes.error_code).toBe(ApiErrorCode.SERVER_ERROR);

    const okProjected = projectPlatformResultQuery({
      data: ok(['a', 'b']),
      isLoading: false,
      isFetching: false,
      isError: false,
      refetch: async () => ({}),
    });
    expect(okProjected.data).toEqual(['a', 'b']);
    expect(okProjected.isError).toBe(false);
    expect(okProjected.problem).toBeNull();

    const errProjected = projectPlatformResultQuery({
      data: err(problem),
      isLoading: false,
      isFetching: false,
      isError: false,
      refetch: async () => ({}),
    });
    expect(errProjected.data).toBeUndefined();
    expect(errProjected.isError).toBe(true);
    expect(errProjected.error).toEqual(problem);

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(apiTokenKeys.all('ten_1'), ok([]));
    qc.setQueryData(webhookKeys.all('ten_1'), err(problem));
    qc.setQueryData(notificationKeys.inApp('ten_1', 'usr_1'), ok([]));
    qc.setQueryData(notificationConfigKeys.preferences('ten_1'), ok([]));
    qc.setQueryData(notificationConfigKeys.templates('ten_1'), err(problem));

    function HooksProbe(): React.ReactElement {
      const tokens = useApiTokensQuery({
        baseUrl: 'https://api.soopa.local',
        tenantId: 'ten_1',
        token: 'tok',
      });
      const webhooks = useWebhooksQuery({
        baseUrl: 'https://api.soopa.local',
        tenantId: 'ten_1',
        token: 'tok',
      });
      const inbox = useNotifications({
        apiUrl: 'https://api.soopa.local',
        tenantId: 'ten_1',
        userId: 'usr_1',
        accessToken: 'tok',
      });
      const prefs = usePreferences({
        apiUrl: 'https://api.soopa.local',
        tenantId: 'ten_1',
        accessToken: 'tok',
      });
      const templates = useTemplates({
        apiUrl: 'https://api.soopa.local',
        tenantId: 'ten_1',
        accessToken: 'tok',
      });
      return React.createElement(
        'div',
        null,
        `tokens:${tokens.data?.length ?? -1}|whErr:${String(webhooks.isError)}|inbox:${inbox.data?.length ?? -1}|prefs:${prefs.data?.length ?? -1}|tplErr:${String(templates.isError)}`,
      );
    }

    const html = renderToStaticMarkup(
      React.createElement(QueryClientProvider, { client: qc }, React.createElement(HooksProbe)),
    );
    expect(html).toContain('tokens:0|whErr:true|inbox:0|prefs:0|tplErr:true');
  });
});
