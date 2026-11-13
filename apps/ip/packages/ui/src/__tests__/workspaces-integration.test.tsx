import { ApiErrorCode, err, ok } from '@soopa/ui';
import { RecordingLoggerFake } from '@soopa/ui/testing';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ipQueryKeys } from '../application/query-keys';
import {
  CatalogAppCategory,
  ConnectionStatus,
  ConnectorRuntimeArchitecture,
  PipelineLayer,
} from '../domain/enums';
import type { IpUserRole } from '../domain/role';
import {
  DeviceLoadCurveLineageDrawer,
  IpCommandCenterPage,
  IpConnectionDetailPage,
  IpConnectionsPage,
  IpIntervalStreamsPage,
  IpStitchDefinitionPage,
  IpStitchesPage,
  IpStitchRunPage,
  IpTracesTimelinePage,
  IpTraceWaterfallPage,
  IpTransformationsPage,
  IpUIProvider,
} from '../index';
import { ConnectionEntitiesSyncTab } from '../presentation/connections/ConnectionEntitiesSyncTab';
import { ConnectionOverviewTab } from '../presentation/connections/ConnectionOverviewTab';
import { ApiProblemBanner } from '../presentation/shared/ApiProblemBanner';
import { TraceWaterfallStageContent } from '../presentation/traces/TraceWaterfallStages';
import { TransformationWorkbenchPanel } from '../presentation/transformations/TransformationWorkbenchPanel';
import {
  createInMemoryIpWorkspaceSeed,
  SEED_CATALOG_APPS,
  SEED_CONNECTION,
  SEED_CONNECTION_ENTITY,
  SEED_CONNECTION_ID,
  SEED_DAILY_TOU_ROLLUPS,
  SEED_DEVICE_ID,
  SEED_DISCOVERED_CATALOG,
  SEED_FEEDER_ID,
  SEED_INTERVAL_COMPLETENESS,
  SEED_INTERVAL_LINEAGE_TRACE,
  SEED_RECONCILIATION_OVERVIEW,
  SEED_RUN_ID,
  SEED_SERVICE_DATE,
  SEED_STITCH,
  SEED_STITCH_DEFINITION,
  SEED_STITCH_RUN,
  SEED_SYNC_RUN,
  SEED_TENANT_ID,
  SEED_TRACE,
  SEED_TRACE_ID,
  SEED_TRACE_LINEAGE,
  SEED_TRANSFORMATION,
  SEED_TRANSFORMERS,
  SEED_WORKFLOW_ID,
} from '../testing';

const SEED_CHILD_TRACE_MARKER = 'trc_2b3c4d5e6f7a8b9c0d1e2f3a';

function createHydratedQueryClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  qc.setQueryData(ipQueryKeys.catalog.apps(SEED_TENANT_ID, undefined), ok(SEED_CATALOG_APPS));
  qc.setQueryData(ipQueryKeys.connections.list(SEED_TENANT_ID, undefined), ok([SEED_CONNECTION]));
  qc.setQueryData(
    ipQueryKeys.connections.detail(SEED_TENANT_ID, SEED_CONNECTION_ID),
    ok(SEED_CONNECTION),
  );
  qc.setQueryData(
    ipQueryKeys.connections.discoveredStreams(SEED_TENANT_ID, SEED_CONNECTION_ID),
    ok(SEED_DISCOVERED_CATALOG),
  );
  qc.setQueryData(
    ipQueryKeys.connections.entities(SEED_TENANT_ID, SEED_CONNECTION_ID),
    ok([SEED_CONNECTION_ENTITY]),
  );
  qc.setQueryData(
    ipQueryKeys.syncRuns.list(SEED_TENANT_ID, SEED_CONNECTION_ID, 40),
    ok([SEED_SYNC_RUN]),
  );
  qc.setQueryData(
    ipQueryKeys.syncRuns.list(SEED_TENANT_ID, SEED_CONNECTION_ID, 50),
    ok([SEED_SYNC_RUN]),
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
    ipQueryKeys.traces.search(SEED_TENANT_ID, 'REC-77410', 75),
    ok(SEED_TRACE_LINEAGE),
  );
  qc.setQueryData(ipQueryKeys.traces.detail(SEED_TENANT_ID, SEED_TRACE_ID, false), ok(SEED_TRACE));
  qc.setQueryData(ipQueryKeys.traces.detail(SEED_TENANT_ID, SEED_TRACE_ID, true), ok(SEED_TRACE));
  qc.setQueryData(
    ipQueryKeys.traces.lineage(SEED_TENANT_ID, SEED_TRACE_ID),
    ok(SEED_TRACE_LINEAGE),
  );
  qc.setQueryData(
    ipQueryKeys.intervals.reconciliation(SEED_TENANT_ID, {
      connectionId: SEED_CONNECTION_ID,
      recentLimit: 20,
    }),
    ok(SEED_RECONCILIATION_OVERVIEW),
  );
  qc.setQueryData(
    ipQueryKeys.intervals.completeness(SEED_TENANT_ID, {
      connectionId: SEED_CONNECTION_ID,
      serviceDate: SEED_SERVICE_DATE,
    }),
    ok(SEED_INTERVAL_COMPLETENESS),
  );
  qc.setQueryData(
    ipQueryKeys.intervals.touRollups(SEED_TENANT_ID, {
      serviceDate: SEED_SERVICE_DATE,
      feederId: undefined,
    }),
    ok(SEED_DAILY_TOU_ROLLUPS),
  );
  qc.setQueryData(
    ipQueryKeys.intervals.deviceLineage(SEED_TENANT_ID, SEED_DEVICE_ID, SEED_SERVICE_DATE),
    ok(SEED_INTERVAL_LINEAGE_TRACE),
  );

  return qc;
}

function renderInIpWorkspace(
  node: React.ReactNode,
  queryClient: QueryClient,
  userRole?: IpUserRole,
): string {
  const harness = createInMemoryIpWorkspaceSeed();
  const logger = new RecordingLoggerFake();

  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <IpUIProvider
        baseUrl="https://api.soopa.local"
        tenantId={SEED_TENANT_ID}
        tenantSlug="acme-tenant"
        repositories={harness.repositories}
        logger={logger}
        navigation={harness.navigation}
        userRole={userRole ?? 'support'}
      >
        {node}
      </IpUIProvider>
    </QueryClientProvider>,
  );
}

describe('IP Presentation Workspaces Narrow Integration', () => {
  it('renders IpCommandCenterPage with Solar Yellow product theme scoping', () => {
    const qc = createHydratedQueryClient();

    const commandCenterHtml = renderInIpWorkspace(<IpCommandCenterPage />, qc);
    expect(commandCenterHtml).toContain('data-product-theme="ip"');
    expect(commandCenterHtml).toContain('Integration Platform');
    expect(commandCenterHtml).toContain('REC-77410');
  });

  it('renders IpTracesTimelinePage with correlation filtering', () => {
    const qc = createHydratedQueryClient();

    const timelineHtml = renderInIpWorkspace(
      <IpTracesTimelinePage initialCorrelationQuery="REC-77410" />,
      qc,
    );
    expect(timelineHtml).toContain('REC-77410');
    expect(timelineHtml).toContain(SEED_TRACE_ID);
  });

  it('renders IpTraceWaterfallPage across all 5 pipeline stages', () => {
    const qc = createHydratedQueryClient();

    const waterfallHtml = renderInIpWorkspace(<IpTraceWaterfallPage traceId={SEED_TRACE_ID} />, qc);
    expect(waterfallHtml).toContain('REC-77410');
    expect(waterfallHtml).toContain('acme_source');
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
    expect(l2Html).toContain('records_alpha');

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
    expect(l3RosettaHtml).toContain('GLX-ENT-44910');
    expect(l3RosettaHtml).toContain('gem_rec_99887766');

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

  it('renders IpConnectionsPage with active connection tabs', () => {
    const qc = createHydratedQueryClient();

    const connectionsHtml = renderInIpWorkspace(<IpConnectionsPage />, qc);
    expect(connectionsHtml).toContain('1 Connected');
    expect(connectionsHtml).toContain('Acme Source API');
    expect(connectionsHtml).toContain('acme_source');

    const activeConnectionsHtml = renderInIpWorkspace(
      <IpConnectionsPage initialTab="active" />,
      qc,
    );
    expect(activeConnectionsHtml).toContain('Acme Primary Workspace');
    expect(activeConnectionsHtml).toContain('Delete Acme Primary Workspace');
  });

  it('renders IpConnectionDetailPage with workspace rename support', async () => {
    const qc = createHydratedQueryClient();

    const connDetailHtml = renderInIpWorkspace(
      <IpConnectionDetailPage connectionId={SEED_CONNECTION_ID} />,
      qc,
    );
    expect(connDetailHtml).toContain('Acme Primary Workspace');
    expect(connDetailHtml).toContain('Connection');
    expect(connDetailHtml).toContain('Entities');
    expect(connDetailHtml).not.toContain('>Data<');
    expect(connDetailHtml).toContain('Connection Details');
    expect(connDetailHtml).toContain('Name');
    expect(connDetailHtml).toContain('Save Changes');
    expect(connDetailHtml).toContain('Delete Connection');

    const harness = createInMemoryIpWorkspaceSeed();
    const relinkRes = await harness.repositories.connections.relinkConnection(
      SEED_TENANT_ID,
      SEED_CONNECTION_ID,
      { newName: 'Acme Renamed Workspace' },
    );
    expect(relinkRes.ok).toBe(true);
    if (relinkRes.ok) {
      expect(relinkRes.value.name).toBe('Acme Renamed Workspace');
      expect(relinkRes.value.publicConfig).toEqual(SEED_CONNECTION.publicConfig);
    }
  });

  it('renders IpTransformationsPage workbench', () => {
    const qc = createHydratedQueryClient();

    const transformationsHtml = renderInIpWorkspace(
      <IpTransformationsPage initialConnectionId={SEED_CONNECTION_ID} />,
      qc,
    );
    expect(transformationsHtml).toContain('acme.record_alpha.to_gem');
    expect(transformationsHtml).toContain('records_alpha');
  });

  it('renders IpStitchesPage with DAG topology views', () => {
    const qc = createHydratedQueryClient();

    const stitchesHtml = renderInIpWorkspace(<IpStitchesPage />, qc);
    expect(stitchesHtml).toContain(SEED_WORKFLOW_ID);

    const dagHtml = renderInIpWorkspace(
      <IpStitchDefinitionPage workflowId={SEED_WORKFLOW_ID} />,
      qc,
    );
    expect(dagHtml).toContain('validate_payload');
    expect(dagHtml).toContain('deliver_globex_sink');

    const runHtml = renderInIpWorkspace(<IpStitchRunPage runId={SEED_RUN_ID} />, qc);
    expect(runHtml).toContain('app:0 · sys:1');
    expect(runHtml).toContain('WAITING');
    expect(runHtml).toContain('validate_payload');
    expect(runHtml).toContain('deliver_globex_sink');
  });

  it('renders degraded ApiProblem banners without throwing', () => {
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

  it('renders Connection Attention Radar for expired credentials', () => {
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
  });

  it('renders ConnectionOverviewTab with ConnectionEntitiesSyncTab', () => {
    const qc = createHydratedQueryClient();

    const overviewHtml = renderInIpWorkspace(
      <ConnectionOverviewTab
        connection={SEED_CONNECTION}
        onProblem={() => undefined}
        onDeactivated={() => undefined}
      />,
      qc,
    );
    expect(overviewHtml).toContain('Connection Details');
    expect(overviewHtml).toContain('Name');
    expect(overviewHtml).toContain('Save Changes');
    expect(overviewHtml).toContain('Deactivate Connection');

    const entitiesTabHtml = renderInIpWorkspace(
      <ConnectionEntitiesSyncTab
        connectionId={SEED_CONNECTION_ID}
        connection={SEED_CONNECTION}
        onOpenTrace={() => undefined}
        onProblem={() => undefined}
      />,
      qc,
    );
    expect(entitiesTabHtml).toContain('Discover Entities...');
    expect(entitiesTabHtml).toContain('records_alpha');
    expect(entitiesTabHtml).toContain('Sync Selected (1)');
  });

  it('renders TransformationWorkbenchPanel dry-run controls', () => {
    const qc = createHydratedQueryClient();

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

  it('excludes DEACTIVATED connections from catalog Connected count badges', () => {
    const qc = createHydratedQueryClient();
    const deactivatedOnlyApp = SEED_CATALOG_APPS[1];
    expect(deactivatedOnlyApp).toBeDefined();
    if (!deactivatedOnlyApp) {
      return;
    }

    qc.setQueryData(
      ipQueryKeys.connections.list(SEED_TENANT_ID, undefined),
      ok([
        SEED_CONNECTION,
        {
          ...SEED_CONNECTION,
          id: 'conn_primary_deactivated',
          name: 'Deactivated Legacy Source Vault',
          status: ConnectionStatus.DEACTIVATED,
          deactivatedAt: '2026-10-30T10:00:00Z',
        },
        {
          ...SEED_CONNECTION,
          id: 'conn_primary_expired',
          name: 'Expired Backup Source Vault',
          status: ConnectionStatus.AUTH_EXPIRED,
        },
        {
          ...SEED_CONNECTION,
          id: 'conn_second_app_deactivated',
          appId: deactivatedOnlyApp.appId,
          name: 'Deactivated Secondary Connector',
          status: ConnectionStatus.DEACTIVATED,
          deactivatedAt: '2026-10-30T11:00:00Z',
        },
      ]),
    );

    const connectionsHtml = renderInIpWorkspace(<IpConnectionsPage />, qc);
    expect(connectionsHtml).toContain('2 Connected');
    expect(connectionsHtml).not.toContain('3 Connected');
    expect(connectionsHtml).not.toContain('1 Connected');
    expect(connectionsHtml).not.toContain('Active Connections:');
    expect(connectionsHtml).not.toContain(SEED_CONNECTION.name);
    expect(connectionsHtml).not.toContain('Expired Backup Source Vault');
    expect(connectionsHtml).not.toContain('Deactivated Legacy Source Vault');
    expect(connectionsHtml).not.toContain('Deactivated Secondary Connector');
  });

  it('renders IpConnectionsPage icons across typed CatalogAppCategory values', () => {
    const qc = createHydratedQueryClient();
    qc.setQueryData(
      ipQueryKeys.catalog.apps(SEED_TENANT_ID, { category: undefined, search: undefined }),
      ok([
        {
          ...SEED_CATALOG_APPS[0]!,
          appId: 'http',
          displayName: 'Universal REST Gateway',
          category: CatalogAppCategory.API,
          runtimeArchitecture: ConnectorRuntimeArchitecture.GENERIC_HTTP,
        },
        {
          ...SEED_CATALOG_APPS[0]!,
          appId: 'sftp',
          displayName: 'SFTP Batch Gateway',
          category: CatalogAppCategory.STORAGE,
          runtimeArchitecture: ConnectorRuntimeArchitecture.NATIVE_PROTOCOL,
        },
        {
          ...SEED_CATALOG_APPS[0]!,
          appId: 'synthetic_sim',
          displayName: 'Synthetic Event Simulator',
          category: CatalogAppCategory.SANDBOX,
          runtimeArchitecture: ConnectorRuntimeArchitecture.NATIVE_SIMULATOR,
        },
      ]),
    );

    const html = renderInIpWorkspace(<IpConnectionsPage />, qc);
    expect(html).toContain('Universal REST Gateway');
    expect(html).toContain('SFTP Batch Gateway');
    expect(html).toContain('Synthetic Event Simulator');
  });

  it('renders Casdoor-styled interval streams workspace', () => {
    const qc = createHydratedQueryClient();

    const intervalsHtml = renderInIpWorkspace(
      <IpIntervalStreamsPage
        initialConnectionId={SEED_CONNECTION_ID}
        initialServiceDate={SEED_SERVICE_DATE}
      />,
      qc,
    );
    expect(intervalsHtml).toContain('High-Frequency Interval Streams');
    expect(intervalsHtml).toContain('ZERO-LOSS BALANCED');
    expect(intervalsHtml).toContain(SEED_FEEDER_ID);
    expect(intervalsHtml).toContain(SEED_DEVICE_ID);
    expect(intervalsHtml).toContain('SETTLE-RCPT-20261029-01');
  });

  it('renders device load curve lineage drawer', () => {
    const drawerHtml = renderToStaticMarkup(
      <DeviceLoadCurveLineageDrawer
        open={true}
        onOpenChange={() => undefined}
        trace={SEED_INTERVAL_LINEAGE_TRACE}
        onOpenBatchTrace={() => undefined}
      />,
    );
    expect(drawerHtml).toContain('Device 96-Slot Load Curve');
    expect(drawerHtml).toContain('Two-Tier Macro-Batch Lineage');
    expect(drawerHtml).toContain('Parquet Row #0');
  });
});
