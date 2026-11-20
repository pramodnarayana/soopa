import { ok } from '@soopa/ui';
import { RecordingLoggerFake } from '@soopa/ui/testing';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ipQueryKeys } from '../application/query-keys';
import {
  useDeleteStitchMutation,
  useRegisterStitchMutation,
  useStitchQuery,
  useToggleStitchStateMutation,
  useUpdateStitchMutation,
} from '../application/use-stitch-queries';
import type { Stitch } from '../domain/stitch';
import { ActiveStitchesTable, IpStitchesPage } from '../presentation/stitches/IpStitchesPage';
import { IpUIProvider } from '../provider/IpUIProvider';
import {
  createInMemoryIpWorkspaceSeed,
  InMemoryStitchRepository,
  SEED_STITCH,
  SEED_STITCH_DEFINITION,
  SEED_STITCH_RUN,
  SEED_TENANT_ID,
} from '../testing';

const SAMPLE_STITCH: Stitch = {
  id: 'stc_device_sync_01',
  name: 'Device Reading Pipeline',
  description: 'Routes device readings to Kafka',
  mappingSpecId: 'spec_device_to_kafka',
  tenantId: SEED_TENANT_ID,
  workflowId: SEED_STITCH_DEFINITION.workflowId,
  workflowVersion: 1,
  canonicalEventType: 'telemetry.device_reading',
  isTrigger: true,
  conditionEventKey: null,
  idempotencyKeyField: 'id',
  concurrencyKeyField: 'device_id',
  resourceHintField: null,
  isActive: true,
};

function createHydratedQueryClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  qc.setQueryData(ipQueryKeys.stitches.definitions(SEED_TENANT_ID), ok([SEED_STITCH_DEFINITION]));
  qc.setQueryData(ipQueryKeys.stitches.list(SEED_TENANT_ID), ok([SAMPLE_STITCH, SEED_STITCH]));
  qc.setQueryData(ipQueryKeys.stitches.runs(SEED_TENANT_ID, { limit: 50 }), ok([SEED_STITCH_RUN]));

  return qc;
}

describe('Stitch CRUD Repository Operations', () => {
  it('performs full in-memory CRUD lifecycle', async () => {
    const repo = new InMemoryStitchRepository([SEED_STITCH_DEFINITION], [SAMPLE_STITCH], []);

    // 1. Get Stitch
    const getRes = await repo.getStitch(SEED_TENANT_ID, SAMPLE_STITCH.id);
    expect(getRes.ok).toBe(true);
    if (getRes.ok) {
      expect(getRes.value.name).toBe('Device Reading Pipeline');
      expect(getRes.value.canonicalEventType).toBe('telemetry.device_reading');
    }

    // 2. Register New Stitch
    const regRes = await repo.registerStitch(SEED_TENANT_ID, {
      stitchId: 'stc_outage_01',
      name: 'Outage Restoration Pipeline',
      description: 'Handles outage alerts',
      workflowId: SEED_STITCH_DEFINITION.workflowId,
      workflowVersion: 1,
      canonicalEventType: 'incident.outage_event',
      isTrigger: true,
      idempotencyKeyField: 'outage_id',
      isActive: true,
    });
    expect(regRes.ok).toBe(true);
    if (regRes.ok) {
      expect(regRes.value.id).toBe('stc_outage_01');
      expect(regRes.value.name).toBe('Outage Restoration Pipeline');
    }

    // List reflects registered stitch
    const listRes = await repo.listStitches(SEED_TENANT_ID);
    expect(listRes.ok).toBe(true);
    if (listRes.ok) {
      expect(listRes.value.map((s) => s.id)).toContain('stc_outage_01');
    }

    // 3. Update Stitch
    const updateRes = await repo.updateStitch(SEED_TENANT_ID, 'stc_outage_01', {
      name: 'Outage Restoration Pipeline v2',
      description: 'Updated SLA and priority',
    });
    expect(updateRes.ok).toBe(true);
    if (updateRes.ok) {
      expect(updateRes.value.name).toBe('Outage Restoration Pipeline v2');
      expect(updateRes.value.description).toBe('Updated SLA and priority');
    }

    // 4. Toggle Stitch State
    const toggleRes = await repo.toggleStitchState(SEED_TENANT_ID, 'stc_outage_01', false);
    expect(toggleRes.ok).toBe(true);
    if (toggleRes.ok) {
      expect(toggleRes.value.isActive).toBe(false);
    }

    // 5. Delete Stitch
    const deleteRes = await repo.deleteStitch(SEED_TENANT_ID, 'stc_outage_01');
    expect(deleteRes.ok).toBe(true);

    const postDeleteGet = await repo.getStitch(SEED_TENANT_ID, 'stc_outage_01');
    expect(postDeleteGet.ok).toBe(false);
  });
});

describe('Stitch CRUD Application Mutations', () => {
  it('executes CRUD mutations via workspace provider', async () => {
    const harness = createInMemoryIpWorkspaceSeed();
    const queryClient = createHydratedQueryClient();
    const logger = new RecordingLoggerFake();

    interface CapturedHooks {
      readonly register: ReturnType<typeof useRegisterStitchMutation>;
      readonly update: ReturnType<typeof useUpdateStitchMutation>;
      readonly toggle: ReturnType<typeof useToggleStitchStateMutation>;
      readonly deleteStitch: ReturnType<typeof useDeleteStitchMutation>;
      readonly stitchDetail: ReturnType<typeof useStitchQuery>;
    }

    let captured: CapturedHooks | undefined;

    function HooksProbe() {
      captured = {
        register: useRegisterStitchMutation(),
        update: useUpdateStitchMutation(),
        toggle: useToggleStitchStateMutation(),
        deleteStitch: useDeleteStitchMutation(),
        stitchDetail: useStitchQuery(SAMPLE_STITCH.id),
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

    expect(captured).toBeDefined();
    if (!captured) return;

    // 1. Register
    const regRes = await captured.register.mutateAsync({
      stitchId: 'stc_probe_01',
      name: 'Probe Pipeline',
      workflowId: SEED_STITCH_DEFINITION.workflowId,
      workflowVersion: 1,
      canonicalEventType: 'probe.event.v1',
      isTrigger: true,
      idempotencyKeyField: 'id',
      isActive: true,
    });
    expect(regRes.ok).toBe(true);

    // 2. Update
    const updateRes = await captured.update.mutateAsync({
      stitchId: 'stc_probe_01',
      input: { name: 'Probe Pipeline Renamed' },
    });
    expect(updateRes.ok).toBe(true);

    // 3. Toggle
    const toggleRes = await captured.toggle.mutateAsync({
      stitchId: 'stc_probe_01',
      isActive: false,
    });
    expect(toggleRes.ok).toBe(true);

    // 4. Delete
    const delRes = await captured.deleteStitch.mutateAsync('stc_probe_01');
    expect(delRes.ok).toBe(true);
  });
});

describe('Stitch CRUD UI Presentation', () => {
  it('renders ActiveStitchesTable with configured pipeline rows', () => {
    const html = renderToStaticMarkup(
      <ActiveStitchesTable
        stitches={[SAMPLE_STITCH, SEED_STITCH]}
        isLoading={false}
        onOpenDefinition={() => {}}
        onEditStitch={() => {}}
        onDeleteStitch={() => {}}
        onToggleState={() => {}}
        onDispatchEvent={() => {}}
      />,
    );

    expect(html).toContain('Device Reading Pipeline');
    expect(html).toContain('telemetry.device_reading');
    expect(html).toContain('spec_device_to_kafka');
    expect(html).toContain('DAG Trigger');
    expect(html).toContain('ACTIVE');
    expect(html).toContain('Actions');
  });

  it('renders IpStitchesPage header with primary actions', () => {
    const harness = createInMemoryIpWorkspaceSeed();
    const qc = createHydratedQueryClient();

    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <IpUIProvider
          baseUrl="http://localhost:8000"
          repositories={harness.repositories}
          navigation={harness.navigation}
          tenantId={SEED_TENANT_ID}
          tenantSlug="test-tenant"
          logger={new RecordingLoggerFake()}
        >
          <IpStitchesPage />
        </IpUIProvider>
      </QueryClientProvider>,
    );

    expect(html).toContain('Stitches &amp; Topological DAG Runs');
    expect(html).toContain('Register Stitch');
    expect(html).toContain('Stitch &amp; Field Mapper');
    expect(html).toContain('Test Event Dispatch');
    expect(html).toContain('Active Stitches');
  });
});
