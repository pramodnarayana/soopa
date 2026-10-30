import { ApiErrorCode, err, LogLevel, ok } from '@soopa/ui';
import { RecordingLoggerFake } from '@soopa/ui/testing';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import {
  type IpQueryView,
  ipQueryKeys,
  logResultOutcome,
  projectResultQuery,
  useBindStreamTransformationMutation,
  useBulkReplayMutation,
  useCatalogAppSpecQuery,
  useCatalogAppsQuery,
  useCheckConnectionMutation,
  useConnectionDetailQuery,
  useConnectionsQuery,
  useConnectionTransformationsQuery,
  useCreateConnectionMutation,
  useDeactivateConnectionMutation,
  useDiscoverCatalogMutation,
  useDispatchStitchEventMutation,
  useIpTraceLineageQuery,
  useIpTraceQuery,
  useModifyAndReplayMutation,
  usePreviewTransformationMutation,
  usePromoteShadowTransformationMutation,
  useRecentTracesQuery,
  useRegisteredTransformersQuery,
  useRegisterStitchMutation,
  useRelinkConnectionMutation,
  useReplayTransactionMutation,
  useResetStreamCheckpointMutation,
  useSearchTracesByCorrelationQuery,
  useStitchDefinitionQuery,
  useStitchDefinitionsQuery,
  useStitchesQuery,
  useStitchRunQuery,
  useStitchRunsQuery,
  useStreamStatesQuery,
  useSyncRunsQuery,
  useTriggerSyncRunMutation,
} from '../application';
import { AuthType, ReplayStage, SyncRunKind, TransformationMode } from '../domain/enums';
import { useIpWorkspace } from '../provider/IpRepositoriesContext';
import { IpUIProvider } from '../provider/IpUIProvider';
import {
  createInMemoryIpWorkspaceSeed,
  SEED_CONNECTION_ID,
  SEED_RUN_ID,
  SEED_TENANT_ID,
  SEED_TRACE_ID,
  SEED_WORKFLOW_ID,
} from '../testing';

describe('Application Layer — Query Keys, Result Projection, Telemetry & InMemory Ports', () => {
  it('constructs deterministic hierarchical query keys across all 6 IP bounded sub-resources', () => {
    expect(ipQueryKeys.all).toEqual(['ip']);
    expect(ipQueryKeys.tenant('ten_1')).toEqual(['ip', 'tenant', 'ten_1']);
    expect(ipQueryKeys.catalog.all()).toEqual(['ip', 'catalog']);
    expect(ipQueryKeys.catalog.spec('itron_ami')).toEqual(['ip', 'catalog', 'spec', 'itron_ami']);
    expect(ipQueryKeys.catalog.apps({ category: 'energy' })).toEqual([
      'ip',
      'catalog',
      'apps',
      'energy',
      '',
    ]);
    expect(ipQueryKeys.connections.all('ten_1')).toEqual(['ip', 'tenant', 'ten_1', 'connections']);
    expect(ipQueryKeys.connections.detail('ten_1', 'conn_1')).toEqual([
      'ip',
      'tenant',
      'ten_1',
      'connections',
      'detail',
      'conn_1',
    ]);
    expect(ipQueryKeys.syncRuns.all('ten_1', 'conn_1')).toEqual([
      'ip',
      'tenant',
      'ten_1',
      'connections',
      'conn_1',
      'sync-runs',
    ]);
    expect(ipQueryKeys.syncRuns.detail('ten_1', 'conn_1', 'run_9')).toEqual([
      'ip',
      'tenant',
      'ten_1',
      'connections',
      'conn_1',
      'sync-runs',
      'detail',
      'run_9',
    ]);
    expect(ipQueryKeys.syncRuns.streamStates('ten_1', 'conn_1')).toEqual([
      'ip',
      'tenant',
      'ten_1',
      'connections',
      'conn_1',
      'stream-states',
    ]);
    expect(ipQueryKeys.transformations.byStream('ten_1', 'conn_1', 'meter_reads')).toEqual([
      'ip',
      'tenant',
      'ten_1',
      'transformations',
      'connection',
      'conn_1',
      'meter_reads',
    ]);
    expect(ipQueryKeys.traces.all('ten_1')).toEqual(['ip', 'tenant', 'ten_1', 'traces']);
    expect(ipQueryKeys.transformations.byConnection('ten_1', 'conn_1')).toEqual([
      'ip',
      'tenant',
      'ten_1',
      'transformations',
      'connection',
      'conn_1',
    ]);
    expect(ipQueryKeys.stitches.run('ten_1', 'run_1')).toEqual([
      'ip',
      'tenant',
      'ten_1',
      'stitches',
      'run',
      'run_1',
    ]);
    expect(ipQueryKeys.traces.detail('ten_1', 'trc_1', true)).toEqual([
      'ip',
      'tenant',
      'ten_1',
      'traces',
      'detail',
      'trc_1',
      true,
    ]);
    expect(ipQueryKeys.traces.recent('ten_1', { minReplayCount: 1, limit: 75 })).toEqual([
      'ip',
      'tenant',
      'ten_1',
      'traces',
      'recent',
      'ALL',
      1,
      75,
    ]);
  });

  it('projects Result<T, ApiProblem> query states cleanly and logs INFO/ERROR mutation outcomes', () => {
    const refetchStub = async () => undefined;
    const okView = projectResultQuery({
      data: ok(['item_1']),
      isLoading: false,
      isFetching: false,
      refetch: refetchStub,
    });
    expect(okView.data).toEqual(['item_1']);
    expect(okView.problem).toBeNull();

    const problem = {
      code: ApiErrorCode.RATE_LIMITED,
      status: 429,
      message: 'Slow down',
      correlationId: 'corr_429',
    };
    const errView = projectResultQuery({
      data: err(problem),
      isLoading: false,
      isFetching: false,
      refetch: refetchStub,
    });
    expect(errView.data).toBeUndefined();
    expect(errView.problem).toEqual(problem);

    const logger = new RecordingLoggerFake().bind({ product: 'ip', tenant_id: SEED_TENANT_ID });
    logResultOutcome(logger, 'ip_trace.replay', ok({ newTraceId: 'trc_new' }), {
      trace_id: SEED_TRACE_ID,
    });
    logResultOutcome(logger, 'ip_trace.replay', err(problem), {
      trace_id: SEED_TRACE_ID,
    });

    expect(logger.entries).toHaveLength(2);
    expect(logger.entries[0]?.level).toBe(LogLevel.INFO);
    expect(logger.entries[0]?.event).toBe('ip_trace.replay.completed');
    expect(logger.entries[1]?.level).toBe(LogLevel.ERROR);
    expect(logger.entries[1]?.event).toBe('ip_trace.replay.failed');
    expect(logger.entries[1]?.attributes.correlation_id).toBe('corr_429');
  });

  it('executes full Liskov-substitutable state transitions across all 6 InMemory repositories', async () => {
    const harness = createInMemoryIpWorkspaceSeed();

    const filteredApps = await harness.catalog.listApps({ search: 'oracle' });
    expect(filteredApps.ok && filteredApps.value).toHaveLength(1);

    const createdConn = await harness.connections.createConnection(SEED_TENANT_ID, {
      appId: 'oracle_mdm',
      name: 'Oracle MDM Prod',
      authType: AuthType.API_KEY,
      publicConfig: {},
      rawCredentials: { api_key: 'sec_99' },
    });
    expect(createdConn.ok).toBe(true);
    if (createdConn.ok) {
      const deactivated = await harness.connections.deactivateConnection(
        SEED_TENANT_ID,
        createdConn.value.id,
      );
      expect(deactivated.ok && deactivated.value.status).toBe('DEACTIVATED');
    }

    const resetState = await harness.syncRuns.resetStreamCheckpoint(
      SEED_TENANT_ID,
      SEED_CONNECTION_ID,
      'meter_reads',
    );
    expect(resetState.ok && resetState.value.recordsSyncedCount).toBe(0);

    const promoted = await harness.transformations.promoteShadowVersion(
      SEED_TENANT_ID,
      SEED_CONNECTION_ID,
      'meter_reads',
    );
    expect(promoted.ok && promoted.value.promotedVersion).toBe(2);

    const rebound = await harness.transformations.bindStreamTransformation(
      SEED_TENANT_ID,
      SEED_CONNECTION_ID,
      'voltage_events',
      {
        transformationId: 'itron.meter_read.to_gem',
        transformationVersion: 2,
        mode: TransformationMode.ACTIVE,
      },
    );
    expect(rebound.ok && rebound.value.wasCreated).toBe(true);
  });

  it('dispatches stitches and filters replayed traces by minReplayCount across InMemory repositories', async () => {
    const harness = createInMemoryIpWorkspaceSeed();

    const dispatched = await harness.stitches.dispatchEvent(SEED_TENANT_ID, {
      canonicalEventType: 'energy.meter_interval.v1',
      payload: { meter_id: 'MTR-77410' },
      correlationId: 'MTR-77410',
    });
    expect(dispatched.ok && dispatched.value.startedRunIds).toHaveLength(1);

    const def = await harness.stitches.getDefinition(SEED_TENANT_ID, SEED_WORKFLOW_ID);
    expect(def.ok && def.value.nodes).toHaveLength(2);

    const bulk = await harness.traces.bulkReplayTransactions(
      SEED_TENANT_ID,
      [SEED_TRACE_ID],
      ReplayStage.RETRY_DELIVER,
    );
    expect(bulk.ok && bulk.value.replayedCount).toBe(1);

    const replayedOnlyList = await harness.traces.listRecentTraces(SEED_TENANT_ID, {
      minReplayCount: 1,
    });
    expect(
      replayedOnlyList.ok && replayedOnlyList.value.every((item) => item.replayCount >= 1),
    ).toBe(true);
  });

  it('executes all TanStack mutation hooks and catalog queries end-to-end with structured telemetry', async () => {
    const harness = createInMemoryIpWorkspaceSeed();
    const logger = new RecordingLoggerFake();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    interface CapturedMutations {
      checkConn: ReturnType<typeof useCheckConnectionMutation>;
      createConn: ReturnType<typeof useCreateConnectionMutation>;
      discoverCat: ReturnType<typeof useDiscoverCatalogMutation>;
      relinkConn: ReturnType<typeof useRelinkConnectionMutation>;
      deactivateConn: ReturnType<typeof useDeactivateConnectionMutation>;
      triggerSync: ReturnType<typeof useTriggerSyncRunMutation>;
      resetCheckpoint: ReturnType<typeof useResetStreamCheckpointMutation>;
      bindTransform: ReturnType<typeof useBindStreamTransformationMutation>;
      promoteShadow: ReturnType<typeof usePromoteShadowTransformationMutation>;
      previewTransform: ReturnType<typeof usePreviewTransformationMutation>;
      registerStitch: ReturnType<typeof useRegisterStitchMutation>;
      dispatchEvent: ReturnType<typeof useDispatchStitchEventMutation>;
      replayTrace: ReturnType<typeof useReplayTransactionMutation>;
      modifyReplay: ReturnType<typeof useModifyAndReplayMutation>;
      bulkReplay: ReturnType<typeof useBulkReplayMutation>;
    }

    let captured: CapturedMutations | null = null;

    function HooksProbe(): React.ReactElement {
      useCatalogAppsQuery();
      useCatalogAppSpecQuery('itron_ami');
      captured = {
        checkConn: useCheckConnectionMutation(),
        createConn: useCreateConnectionMutation(),
        discoverCat: useDiscoverCatalogMutation(SEED_CONNECTION_ID),
        relinkConn: useRelinkConnectionMutation(SEED_CONNECTION_ID),
        deactivateConn: useDeactivateConnectionMutation(SEED_CONNECTION_ID),
        triggerSync: useTriggerSyncRunMutation(SEED_CONNECTION_ID),
        resetCheckpoint: useResetStreamCheckpointMutation(SEED_CONNECTION_ID),
        bindTransform: useBindStreamTransformationMutation(),
        promoteShadow: usePromoteShadowTransformationMutation(),
        previewTransform: usePreviewTransformationMutation(),
        registerStitch: useRegisterStitchMutation(),
        dispatchEvent: useDispatchStitchEventMutation(),
        replayTrace: useReplayTransactionMutation(),
        modifyReplay: useModifyAndReplayMutation(),
        bulkReplay: useBulkReplayMutation(),
      };
      return React.createElement('div', null, 'probe');
    }

    renderToStaticMarkup(
      React.createElement(
        QueryClientProvider,
        { client: queryClient },
        React.createElement(IpUIProvider, {
          baseUrl: 'https://api.soopa.local',
          tenantId: SEED_TENANT_ID,
          repositories: harness.repositories,
          logger,
          navigation: harness.navigation,
          children: React.createElement(HooksProbe),
        }),
      ),
    );

    // Also verify default HttpRepositoriesBundle creation inside IpUIProvider when repositories prop is omitted
    const defaultProviderHtml = renderToStaticMarkup(
      React.createElement(
        QueryClientProvider,
        { client: queryClient },
        React.createElement(IpUIProvider, {
          baseUrl: 'https://api.soopa.local',
          tenantId: SEED_TENANT_ID,
          token: 'jwt_tok',
          navigation: harness.navigation,
          children: React.createElement('span', null, 'default-bundle'),
        }),
      ),
    );
    expect(defaultProviderHtml).toContain('default-bundle');

    if (!captured) {
      throw new Error('Expected HooksProbe to capture mutations');
    }
    const api: CapturedMutations = captured;

    await api.checkConn.mutateAsync({
      appId: 'itron_ami',
      authType: AuthType.OAUTH2,
      publicConfig: {},
      rawCredentials: {},
    });
    await api.createConn.mutateAsync({
      appId: 'oracle_mdm',
      name: 'Oracle Vault',
      authType: AuthType.API_KEY,
      publicConfig: {},
      rawCredentials: { api_key: 'k' },
    });
    await api.discoverCat.mutateAsync();
    await api.relinkConn.mutateAsync({ newName: 'Itron Renamed' });
    await api.triggerSync.mutateAsync({
      streamName: 'meter_reads',
      forcedKind: SyncRunKind.INCREMENTAL,
    });
    await api.resetCheckpoint.mutateAsync('meter_reads');
    await api.bindTransform.mutateAsync({
      connectionId: SEED_CONNECTION_ID,
      stream: 'meter_reads',
      input: {
        transformationId: 'itron.meter_read.to_gem',
        transformationVersion: 1,
        mode: TransformationMode.SHADOW,
        shadowTransformationVersion: 2,
      },
    });
    await api.promoteShadow.mutateAsync({
      connectionId: SEED_CONNECTION_ID,
      stream: 'meter_reads',
    });
    await api.previewTransform.mutateAsync({
      connectionId: SEED_CONNECTION_ID,
      stream: 'meter_reads',
      transformationId: 'itron.meter_read.to_gem',
      transformationVersion: 2,
      recordKey: 'MTR-77410',
      samplePayload: { kwh: 42 },
    });
    await api.registerStitch.mutateAsync({
      workflowId: SEED_WORKFLOW_ID,
      workflowVersion: 1,
      canonicalEventType: 'energy.meter_interval.v1',
      isTrigger: true,
      idempotencyKeyField: 'source_id',
      isActive: true,
    });
    await api.dispatchEvent.mutateAsync({
      canonicalEventType: 'energy.meter_interval.v1',
      payload: { source_id: 'MTR-77410' },
      correlationId: 'MTR-77410',
    });
    await api.replayTrace.mutateAsync({
      traceId: SEED_TRACE_ID,
      stage: ReplayStage.RETRY_DELIVER,
    });
    await api.modifyReplay.mutateAsync({
      traceId: SEED_TRACE_ID,
      stage: ReplayStage.RETRY_INGEST,
      modifiedPayload: { meter_id: 'MTR-77410' },
    });
    await api.bulkReplay.mutateAsync({
      traceIds: [SEED_TRACE_ID],
      stage: ReplayStage.RETRY_DELIVER,
    });
    await api.deactivateConn.mutateAsync();

    expect(logger.entries.length).toBeGreaterThanOrEqual(15);
    expect(logger.entries.every((entry) => entry.level === LogLevel.INFO)).toBe(true);
  });

  it('executes all 17 TanStack query hooks against InMemory repositories and hydrates IpQueryView', async () => {
    const harness = createInMemoryIpWorkspaceSeed();
    const logger = new RecordingLoggerFake();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    let capturedViews: readonly IpQueryView<unknown>[] = [];

    function AllQueriesProbe(): React.ReactElement {
      capturedViews = [
        useCatalogAppsQuery({ category: 'energy' }),
        useCatalogAppSpecQuery('itron_ami'),
        useConnectionsQuery('ACTIVE'),
        useConnectionDetailQuery(SEED_CONNECTION_ID),
        useSyncRunsQuery(SEED_CONNECTION_ID, 20),
        useStreamStatesQuery(SEED_CONNECTION_ID),
        useRegisteredTransformersQuery(),
        useConnectionTransformationsQuery(SEED_CONNECTION_ID),
        useStitchDefinitionsQuery(),
        useStitchDefinitionQuery(SEED_WORKFLOW_ID, 1),
        useStitchesQuery(),
        useStitchRunsQuery({ workflowId: SEED_WORKFLOW_ID }),
        useStitchRunQuery(SEED_RUN_ID),
        useRecentTracesQuery({ limit: 15 }),
        useSearchTracesByCorrelationQuery('MTR-77410', 25),
        useIpTraceQuery(SEED_TRACE_ID, true),
        useIpTraceLineageQuery(SEED_TRACE_ID),
      ];
      return React.createElement('div', null, 'queries-probe');
    }

    const tree = React.createElement(
      QueryClientProvider,
      { client: queryClient },
      React.createElement(IpUIProvider, {
        baseUrl: 'https://api.soopa.local',
        tenantId: SEED_TENANT_ID,
        repositories: harness.repositories,
        logger,
        navigation: harness.navigation,
        children: React.createElement(AllQueriesProbe),
      }),
    );

    renderToStaticMarkup(tree);
    expect(capturedViews).toHaveLength(17);

    const cachedQueries = queryClient.getQueryCache().getAll();
    expect(cachedQueries.length).toBeGreaterThanOrEqual(17);
    await Promise.all(cachedQueries.map((query) => query.fetch()));

    renderToStaticMarkup(tree);
    expect(capturedViews.every((view) => view.data !== undefined)).toBe(true);
    expect(capturedViews.every((view) => view.problem === null)).toBe(true);
  });

  it('handles Result Err mutation outcomes without throwing and guards missing IpUIProvider', async () => {
    function OrphanConsumer(): React.ReactElement {
      useIpWorkspace();
      return React.createElement('div');
    }
    expect(() => renderToStaticMarkup(React.createElement(OrphanConsumer))).toThrow(
      'useIpWorkspace must be used inside <IpUIProvider>.',
    );

    const harness = createInMemoryIpWorkspaceSeed();
    const logger = new RecordingLoggerFake();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    interface FailureProbeApi {
      discoverMissing: ReturnType<typeof useDiscoverCatalogMutation>;
      relinkMissing: ReturnType<typeof useRelinkConnectionMutation>;
      deactivateMissing: ReturnType<typeof useDeactivateConnectionMutation>;
      resetMissing: ReturnType<typeof useResetStreamCheckpointMutation>;
      promoteMissing: ReturnType<typeof usePromoteShadowTransformationMutation>;
      replayMissing: ReturnType<typeof useReplayTransactionMutation>;
      modifyMissing: ReturnType<typeof useModifyAndReplayMutation>;
    }
    let failureApi: FailureProbeApi | null = null;

    function FailureHooksProbe(): React.ReactElement {
      useCatalogAppSpecQuery(null);
      useConnectionTransformationsQuery(null);
      failureApi = {
        discoverMissing: useDiscoverCatalogMutation('conn_missing'),
        relinkMissing: useRelinkConnectionMutation('conn_missing'),
        deactivateMissing: useDeactivateConnectionMutation('conn_missing'),
        resetMissing: useResetStreamCheckpointMutation('conn_missing'),
        promoteMissing: usePromoteShadowTransformationMutation(),
        replayMissing: useReplayTransactionMutation(),
        modifyMissing: useModifyAndReplayMutation(),
      };
      return React.createElement('div', null, 'failure-probe');
    }

    renderToStaticMarkup(
      React.createElement(
        QueryClientProvider,
        { client: queryClient },
        React.createElement(IpUIProvider, {
          baseUrl: 'https://api.soopa.local',
          tenantId: SEED_TENANT_ID,
          repositories: harness.repositories,
          logger,
          navigation: harness.navigation,
          children: React.createElement(FailureHooksProbe),
        }),
      ),
    );

    if (!failureApi) {
      throw new Error('Expected FailureHooksProbe to mount');
    }
    const api: FailureProbeApi = failureApi;

    expect((await api.discoverMissing.mutateAsync()).ok).toBe(false);
    expect((await api.relinkMissing.mutateAsync({ newName: 'Nope' })).ok).toBe(false);
    expect((await api.deactivateMissing.mutateAsync()).ok).toBe(false);
    expect((await api.resetMissing.mutateAsync('missing_stream')).ok).toBe(false);
    expect(
      (
        await api.promoteMissing.mutateAsync({
          connectionId: SEED_CONNECTION_ID,
          stream: 'unconfigured_stream',
        })
      ).ok,
    ).toBe(false);
    expect(
      (
        await api.replayMissing.mutateAsync({
          traceId: 'trc_missing',
          stage: ReplayStage.RETRY_DELIVER,
        })
      ).ok,
    ).toBe(false);
    expect(
      (
        await api.modifyMissing.mutateAsync({
          traceId: 'trc_missing',
          stage: ReplayStage.RETRY_INGEST,
          modifiedPayload: {},
        })
      ).ok,
    ).toBe(false);

    expect(logger.entries).toHaveLength(7);
    expect(logger.entries.every((entry) => entry.level === LogLevel.ERROR)).toBe(true);
  });
});
