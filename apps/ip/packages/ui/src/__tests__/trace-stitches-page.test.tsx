import { ok } from '@soopa/ui';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ipQueryKeys } from '../application/query-keys';
import { IpTraceStitchesPage } from '../presentation/traces/IpTraceStitchesPage';
import { IpUIProvider } from '../provider/IpUIProvider';
import {
  createInMemoryIpWorkspaceSeed,
  SEED_STITCH_DEFINITION,
  SEED_STITCH_RUN,
  SEED_TENANT_ID,
  SEED_TRACE,
  SEED_TRACE_ID,
  SEED_WORKFLOW_ID,
} from '../testing';

function createHydratedQueryClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  qc.setQueryData(ipQueryKeys.traces.detail(SEED_TENANT_ID, SEED_TRACE_ID, true), ok(SEED_TRACE));
  qc.setQueryData(ipQueryKeys.traces.detail(SEED_TENANT_ID, SEED_TRACE_ID, false), ok(SEED_TRACE));
  qc.setQueryData(
    ipQueryKeys.stitches.runs(SEED_TENANT_ID, { traceId: SEED_TRACE_ID }),
    ok([SEED_STITCH_RUN]),
  );
  qc.setQueryData(ipQueryKeys.stitches.definitions(SEED_TENANT_ID), ok([SEED_STITCH_DEFINITION]));
  qc.setQueryData(ipQueryKeys.stitches.list(SEED_TENANT_ID), ok([]));

  return qc;
}

function renderPage(ui: React.ReactElement, queryClient = createHydratedQueryClient()): string {
  const bundle = createInMemoryIpWorkspaceSeed();
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <IpUIProvider
        baseUrl="https://api.soopa.local"
        tenantId={SEED_TENANT_ID}
        tenantSlug="test-tenant"
        repositories={bundle.repositories}
        navigation={bundle.navigation}
      >
        {ui}
      </IpUIProvider>
    </QueryClientProvider>,
  );
}

describe('IpTraceStitchesPage', () => {
  it('renders context ribbon with trace identifier', () => {
    const html = renderPage(<IpTraceStitchesPage traceId={SEED_TRACE_ID} />);
    expect(html).toContain('Back to Records');
    expect(html).toContain(SEED_TRACE_ID);
    expect(html).toContain('Full Trace Waterfall');
  });

  it('displays tabbed stitches for attached workflow runs', () => {
    const html = renderPage(<IpTraceStitchesPage traceId={SEED_TRACE_ID} />);
    expect(html).toContain('Stitches');
    expect(html).toContain('Sync Alpha To Sink Stitch');
  });

  it('renders interactive DAG canvas for active stitch', () => {
    const html = renderPage(<IpTraceStitchesPage traceId={SEED_TRACE_ID} />);
    expect(html).toContain('Workflow:');
    expect(html).toContain(SEED_WORKFLOW_ID);
  });

  it('renders informative empty state when no stitches attach to trace', () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(
      ipQueryKeys.traces.detail(SEED_TENANT_ID, 'empty-trace', true),
      ok({
        ...SEED_TRACE,
        traceId: 'empty-trace',
        outboundRecords: [],
      }),
    );
    qc.setQueryData(
      ipQueryKeys.traces.detail(SEED_TENANT_ID, 'empty-trace', false),
      ok({
        ...SEED_TRACE,
        traceId: 'empty-trace',
        outboundRecords: [],
      }),
    );
    qc.setQueryData(ipQueryKeys.stitches.runs(SEED_TENANT_ID, { traceId: 'empty-trace' }), ok([]));
    qc.setQueryData(ipQueryKeys.stitches.definitions(SEED_TENANT_ID), ok([]));
    qc.setQueryData(ipQueryKeys.stitches.list(SEED_TENANT_ID), ok([]));

    const html = renderPage(<IpTraceStitchesPage traceId="empty-trace" />, qc);
    expect(html).toContain('No Workflow Stitches Attached');
    expect(html).toContain('Return to Data Explorer');
  });
});
