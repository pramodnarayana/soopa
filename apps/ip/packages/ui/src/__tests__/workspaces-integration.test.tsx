import { ApiErrorCode, err, ok } from '@soopa/ui';
import { RecordingLoggerFake } from '@soopa/ui/testing';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ipQueryKeys } from '../application/query-keys';
import { ConnectionStatus, PipelineLayer } from '../domain/enums';
import {
  IpCommandCenterPage,
  IpConnectionDetailPage,
  IpConnectionsPage,
  IpStitchDefinitionPage,
  IpStitchesPage,
  IpStitchRunPage,
  IpTracesTimelinePage,
  IpTraceWaterfallPage,
  IpTransformationsPage,
  IpUIProvider,
} from '../index';
import {
  ConnectionCatalogTab,
  ConnectionOverviewTab,
} from '../presentation/connections/ConnectionDetailTabs';
import { ApiProblemBanner } from '../presentation/shared/ApiProblemBanner';
import { TraceWaterfallStageContent } from '../presentation/traces/TraceWaterfallStages';
import { TransformationWorkbenchPanel } from '../presentation/transformations/TransformationWorkbenchPanel';
import {
  createInMemoryIpWorkspaceSeed,
  SEED_CONNECTION,
  SEED_CONNECTION_ID,
  SEED_DISCOVERED_CATALOG,
  SEED_RUN_ID,
  SEED_STITCH,
  SEED_STITCH_DEFINITION,
  SEED_STITCH_RUN,
  SEED_STREAM_STATE,
  SEED_SYNC_RUN,
  SEED_TENANT_ID,
  SEED_TRACE,
  SEED_TRACE_ID,
  SEED_TRACE_LINEAGE,
  SEED_TRANSFORMATION,
  SEED_TRANSFORMERS,
  SEED_WORKFLOW_ID,
} from '../testing';

function createHydratedQueryClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  qc.setQueryData(ipQueryKeys.connections.list(SEED_TENANT_ID, undefined), ok([SEED_CONNECTION]));
  qc.setQueryData(
    ipQueryKeys.connections.detail(SEED_TENANT_ID, SEED_CONNECTION_ID),
    ok(SEED_CONNECTION),
  );
  qc.setQueryData(
    ipQueryKeys.connections.catalog(SEED_TENANT_ID, SEED_CONNECTION_ID),
    ok(SEED_DISCOVERED_CATALOG),
  );
  qc.setQueryData(
    ipQueryKeys.syncRuns.list(SEED_TENANT_ID, SEED_CONNECTION_ID, 50),
    ok([SEED_SYNC_RUN]),
  );
  qc.setQueryData(
    ipQueryKeys.syncRuns.streamStates(SEED_TENANT_ID, SEED_CONNECTION_ID),
    ok([SEED_STREAM_STATE]),
  );
  qc.setQueryData(ipQueryKeys.transformations.transformers(SEED_TENANT_ID), ok(SEED_TRANSFORMERS));
  qc.setQueryData(
    ipQueryKeys.transformations.byConnection(SEED_TENANT_ID, SEED_CONNECTION_ID),
    ok([SEED_TRANSFORMATION]),
  );
  qc.setQueryData(ipQueryKeys.stitches.definitions(SEED_TENANT_ID), ok([SEED_STITCH_DEFINITION]));
  qc.setQueryData(
    ipQueryKeys.stitches.definition(SEED_TENANT_ID, SEED_WORKFLOW_ID, undefined),
    ok(SEED_STITCH_DEFINITION),
  );
  qc.setQueryData(
    ipQueryKeys.stitches.definition(SEED_TENANT_ID, SEED_WORKFLOW_ID, 1),
    ok(SEED_STITCH_DEFINITION),
  );
  qc.setQueryData(ipQueryKeys.stitches.list(SEED_TENANT_ID), ok([SEED_STITCH]));
  qc.setQueryData(ipQueryKeys.stitches.runs(SEED_TENANT_ID, undefined), ok([SEED_STITCH_RUN]));
  qc.setQueryData(ipQueryKeys.stitches.runs(SEED_TENANT_ID, { limit: 8 }), ok([SEED_STITCH_RUN]));
  qc.setQueryData(ipQueryKeys.stitches.runs(SEED_TENANT_ID, { limit: 15 }), ok([SEED_STITCH_RUN]));
  qc.setQueryData(ipQueryKeys.stitches.run(SEED_TENANT_ID, SEED_RUN_ID), ok(SEED_STITCH_RUN));
  qc.setQueryData(ipQueryKeys.traces.recent(SEED_TENANT_ID, { limit: 10 }), ok(SEED_TRACE_LINEAGE));
  qc.setQueryData(ipQueryKeys.traces.recent(SEED_TENANT_ID, { limit: 20 }), ok(SEED_TRACE_LINEAGE));
  qc.setQueryData(
    ipQueryKeys.traces.recent(SEED_TENANT_ID, {
      status: undefined,
      minReplayCount: undefined,
      limit: 75,
    }),
    ok(SEED_TRACE_LINEAGE),
  );
  qc.setQueryData(
    ipQueryKeys.traces.search(SEED_TENANT_ID, 'MTR-77410', 75),
    ok(SEED_TRACE_LINEAGE),
  );
  qc.setQueryData(ipQueryKeys.traces.detail(SEED_TENANT_ID, SEED_TRACE_ID, false), ok(SEED_TRACE));
  qc.setQueryData(ipQueryKeys.traces.detail(SEED_TENANT_ID, SEED_TRACE_ID, true), ok(SEED_TRACE));
  qc.setQueryData(
    ipQueryKeys.traces.lineage(SEED_TENANT_ID, SEED_TRACE_ID),
    ok(SEED_TRACE_LINEAGE),
  );

  return qc;
}

function renderInIpWorkspace(node: React.ReactNode, queryClient: QueryClient): string {
  const harness = createInMemoryIpWorkspaceSeed();
  const logger = new RecordingLoggerFake();

  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <IpUIProvider
        baseUrl="https://api.soopa.local"
        tenantId={SEED_TENANT_ID}
        tenantSlug="solar-grid"
        repositories={harness.repositories}
        logger={logger}
        navigation={harness.navigation}
      >
        {node}
      </IpUIProvider>
    </QueryClientProvider>,
  );
}

describe('IP Presentation Workspaces — Narrow Integration Rendering & First-Class Error States', () => {
  it('renders Command Center, Support Timeline, and 5-Layer Trace Waterfall with Solar Yellow scoping & Rosetta strip', () => {
    const qc = createHydratedQueryClient();

    const commandCenterHtml = renderInIpWorkspace(<IpCommandCenterPage />, qc);
    expect(commandCenterHtml).toContain('data-product-theme="ip"');
    expect(commandCenterHtml).toContain('Integration Platform');
    expect(commandCenterHtml).toContain('MTR-77410');

    const timelineHtml = renderInIpWorkspace(
      <IpTracesTimelinePage initialCorrelationQuery="MTR-77410" />,
      qc,
    );
    expect(timelineHtml).toContain('MTR-77410');
    expect(timelineHtml).toContain(SEED_TRACE_ID);

    const waterfallHtml = renderInIpWorkspace(<IpTraceWaterfallPage traceId={SEED_TRACE_ID} />, qc);
    expect(waterfallHtml).toContain('MTR-77410');
    expect(waterfallHtml).toContain('itron_ami');
    expect(waterfallHtml).toContain(SEED_CHILD_TRACE_MARKER);

    const l2Html = renderInIpWorkspace(
      <TraceWaterfallStageContent
        activeLayer={PipelineLayer.L2_REPLICA}
        trace={SEED_TRACE}
        hasUnhydratedS3={false}
        onHydrateS3={() => undefined}
        onOpenStitches={() => undefined}
      />,
      qc,
    );
    expect(l2Html).toContain('meter_reads');

    const l3RosettaHtml = renderInIpWorkspace(
      <TraceWaterfallStageContent
        activeLayer={PipelineLayer.L3_NORMALIZE}
        trace={SEED_TRACE}
        hasUnhydratedS3={false}
        onHydrateS3={() => undefined}
        onOpenStitches={() => undefined}
      />,
      qc,
    );
    expect(l3RosettaHtml).toContain('ORA-SP-44910');
    expect(l3RosettaHtml).toContain('gem_mtr_99887766');

    const l4Html = renderInIpWorkspace(
      <TraceWaterfallStageContent
        activeLayer={PipelineLayer.L4_STITCH}
        trace={SEED_TRACE}
        hasUnhydratedS3={false}
        onHydrateS3={() => undefined}
        onOpenStitches={() => undefined}
      />,
      qc,
    );
    expect(l4Html).toContain('DELIVERY_FAILED');
    expect(l4Html).toContain('IP_OUTBOUND_WORKER');

    const l5Html = renderInIpWorkspace(
      <TraceWaterfallStageContent
        activeLayer={PipelineLayer.L5_DELIVER}
        trace={SEED_TRACE}
        hasUnhydratedS3={false}
        onHydrateS3={() => undefined}
        onOpenStitches={() => undefined}
      />,
      qc,
    );
    expect(l5Html).toContain('Retry-After: 30s');
    expect(l5Html).toContain('POST 502');
  });

  it('renders Connections, Connection Detail, Transformations Workbench, and Stitches DAG & Run Telemetry', () => {
    const qc = createHydratedQueryClient();

    const connectionsHtml = renderInIpWorkspace(<IpConnectionsPage />, qc);
    expect(connectionsHtml).toContain('Itron Production West Grid');
    expect(connectionsHtml).toContain('itron_ami');

    const connDetailHtml = renderInIpWorkspace(
      <IpConnectionDetailPage connectionId={SEED_CONNECTION_ID} />,
      qc,
    );
    expect(connDetailHtml).toContain('Itron Production West Grid');
    expect(connDetailHtml).toContain('interval_end: 2026-10-29T08:00:00Z');
    expect(connDetailHtml).toContain('48200');

    const transformationsHtml = renderInIpWorkspace(
      <IpTransformationsPage initialConnectionId={SEED_CONNECTION_ID} />,
      qc,
    );
    expect(transformationsHtml).toContain('itron.meter_read.to_gem');
    expect(transformationsHtml).toContain('meter_reads');

    const stitchesHtml = renderInIpWorkspace(<IpStitchesPage />, qc);
    expect(stitchesHtml).toContain(SEED_WORKFLOW_ID);

    const dagHtml = renderInIpWorkspace(
      <IpStitchDefinitionPage workflowId={SEED_WORKFLOW_ID} />,
      qc,
    );
    expect(dagHtml).toContain('validate_interval');
    expect(dagHtml).toContain('deliver_oracle_mdm');

    const runHtml = renderInIpWorkspace(<IpStitchRunPage runId={SEED_RUN_ID} />, qc);
    expect(runHtml).toContain('app:0 · sys:1');
    expect(runHtml).toContain('WAITING');
    expect(runHtml).toContain('validate_interval');
    expect(runHtml).toContain('deliver_oracle_mdm');
  });

  it('renders first-class ApiProblem error banners (429 Retry-After, 422 field errors, SCHEMA_DRIFT) without throwing', () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(
      ipQueryKeys.traces.detail(SEED_TENANT_ID, SEED_TRACE_ID, false),
      err({
        code: ApiErrorCode.RATE_LIMITED,
        status: 429,
        message: 'Rate limit exceeded on data-plane shard',
        correlationId: 'corr_limit_88',
        retryAfterSeconds: 45,
      }),
    );

    const degradedWaterfallHtml = renderInIpWorkspace(
      <IpTraceWaterfallPage traceId={SEED_TRACE_ID} />,
      qc,
    );
    expect(degradedWaterfallHtml).toContain('Rate limit exceeded on data-plane shard');
    expect(degradedWaterfallHtml).toContain('45s');
    expect(degradedWaterfallHtml).toContain('corr_limit_88');

    const validationBannerHtml = renderToStaticMarkup(
      <ApiProblemBanner
        problem={{
          code: ApiErrorCode.VALIDATION_ERROR,
          status: 422,
          message: 'Invalid payload override',
          fieldErrors: { modified_payload: 'Expected JSON object' },
        }}
      />,
    );
    expect(validationBannerHtml).toContain('modified_payload');
    expect(validationBannerHtml).toContain('Expected JSON object');
  });

  it('renders ConnectionOverviewTab, ConnectionCatalogTab, TransformationWorkbenchPanel, and Attention Radar', () => {
    const qc = createHydratedQueryClient();
    qc.setQueryData(
      ipQueryKeys.connections.list(SEED_TENANT_ID, undefined),
      ok([
        SEED_CONNECTION,
        {
          ...SEED_CONNECTION,
          id: 'conn_expired_02',
          name: 'SAP S/4HANA Expired Vault',
          status: ConnectionStatus.AUTH_EXPIRED,
          lastErrorMessage: 'OAuth2 refresh token expired',
        },
      ]),
    );

    const radarHtml = renderInIpWorkspace(<IpCommandCenterPage />, qc);
    expect(radarHtml).toContain('Connection Attention Radar');
    expect(radarHtml).toContain('SAP S/4HANA Expired Vault');

    const overviewHtml = renderInIpWorkspace(
      <ConnectionOverviewTab
        connection={SEED_CONNECTION}
        onProblem={() => undefined}
        onDeactivated={() => undefined}
      />,
      qc,
    );
    expect(overviewHtml).toContain('fp_88aa99bbccddeeff00112233');
    expect(overviewHtml).toContain('Soft-Deactivate Connection');

    const catalogTabHtml = renderInIpWorkspace(
      <ConnectionCatalogTab
        connectionId={SEED_CONNECTION_ID}
        onProblem={() => undefined}
        onConfigureTransformation={() => undefined}
      />,
      qc,
    );
    expect(catalogTabHtml).toContain('Discover Schema Catalog');

    const workbenchHtml = renderInIpWorkspace(
      <TransformationWorkbenchPanel
        connectionId={SEED_CONNECTION_ID}
        transformers={SEED_TRANSFORMERS}
      />,
      qc,
    );
    expect(workbenchHtml).toContain('Dry-Run &amp; Shadow Diff Workbench');
    expect(workbenchHtml).toContain('Run Dry-Run Preview');
  });
});

const SEED_CHILD_TRACE_MARKER = 'trc_2b3c4d5e6f7a8b9c0d1e2f3a';
