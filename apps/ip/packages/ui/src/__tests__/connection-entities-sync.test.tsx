import { ApiErrorCode, type ApiProblem, err, ok } from '@soopa/ui';
import { RecordingLoggerFake } from '@soopa/ui/testing';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ipQueryKeys } from '../application/query-keys';
import { buildIngressWebhookUrl } from '../domain/connection';
import { AuthType, ConnectionHandshakeStatus, UNIVERSAL_SIMULATOR_APP_ID } from '../domain/enums';
import {
  ActiveConnectionCard,
  shouldActivateCardOnKeyDown,
} from '../presentation/connections/ActiveConnectionCard';
import {
  ConnectionEntitiesSyncTab,
  ConnectionOverviewTab,
  commitStreamScheduleConfigUpdate,
} from '../presentation/connections/ConnectionDetailTabs';
import {
  CreateSimulatorEntityForm,
  findDuplicateSimulatorEntityError,
  inferSimulatorEntityNameFromFilename,
  parseSimulatorBlueprint,
} from '../presentation/connections/CreateSimulatorEntityModal';
import { IpUIProvider } from '../provider/IpUIProvider';
import {
  createInMemoryIpWorkspaceSeed,
  SEED_CATALOG_APPS,
  SEED_CONNECTION,
  SEED_CONNECTION_ID,
  SEED_SIMULATOR_APP_SPEC,
  SEED_SIMULATOR_ENTITY,
  SEED_SIMULATOR_SANDBOX_ID,
  SEED_STREAM_STATE,
  SEED_SYNC_RUN,
  SEED_TENANT_ID,
} from '../testing';

function createEntitiesQueryClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });

  qc.setQueryData(ipQueryKeys.catalog.apps(SEED_TENANT_ID, undefined), ok(SEED_CATALOG_APPS));
  qc.setQueryData(
    ipQueryKeys.catalog.spec(SEED_TENANT_ID, UNIVERSAL_SIMULATOR_APP_ID),
    ok(SEED_SIMULATOR_APP_SPEC),
  );
  qc.setQueryData(
    ipQueryKeys.simulator.entities(SEED_TENANT_ID, SEED_SIMULATOR_SANDBOX_ID),
    ok([SEED_SIMULATOR_ENTITY]),
  );
  qc.setQueryData(
    ipQueryKeys.syncRuns.streamStates(SEED_TENANT_ID, SEED_CONNECTION_ID),
    ok([SEED_STREAM_STATE]),
  );
  qc.setQueryData(
    ipQueryKeys.syncRuns.list(SEED_TENANT_ID, SEED_CONNECTION_ID, 40),
    ok([SEED_SYNC_RUN]),
  );
  qc.setQueryData(
    ipQueryKeys.connections.catalog(SEED_TENANT_ID, SEED_CONNECTION_ID),
    ok({
      connectionId: SEED_CONNECTION_ID,
      catalogVersion: 1,
      catalogHash: 'hash-init',
      discoveredAt: '2026-11-05T10:00:00Z',
      streams: [],
    }),
  );
  return qc;
}

function renderEntitiesTab(node: React.ReactNode, queryClient: QueryClient): string {
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
        defaultUserRole="support"
      >
        {node}
      </IpUIProvider>
    </QueryClientProvider>,
  );
}

describe('ConnectionEntitiesSyncTab Control Plane', () => {
  it('renders ConnectionEntitiesSyncTab entity table columns for configured streams', () => {
    const qc = createEntitiesQueryClient();
    const html = renderEntitiesTab(
      <ConnectionEntitiesSyncTab
        connectionId={SEED_CONNECTION_ID}
        connection={SEED_CONNECTION}
        onOpenTrace={() => undefined}
        onProblem={() => undefined}
      />,
      qc,
    );

    expect(html).toContain('Entities');
    expect(html).toContain('Discover Entities...');
    expect(html).toContain('Search Entities');
    expect(html).toContain('Sync From');
    expect(html).toContain('Schedule');
    expect(html).toContain('Status');
    expect(html).toContain('Actions');
    expect(html).toContain('records_alpha');
  });

  it('renders ConnectionEntitiesSyncTab batch sync selection controls', () => {
    const qc = createEntitiesQueryClient();
    const html = renderEntitiesTab(
      <ConnectionEntitiesSyncTab
        connectionId={SEED_CONNECTION_ID}
        connection={SEED_CONNECTION}
        onOpenTrace={() => undefined}
        onProblem={() => undefined}
      />,
      qc,
    );

    expect(html).toContain('Sync Selected (1)');
  });

  it('renders clean state with visible TableHeader for fresh connections', () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    qc.setQueryData(ipQueryKeys.syncRuns.streamStates(SEED_TENANT_ID, 'conn_new_clean'), ok([]));
    qc.setQueryData(
      ipQueryKeys.connections.catalog(SEED_TENANT_ID, 'conn_new_clean'),
      ok({
        connectionId: 'conn_new_clean',
        catalogVersion: 1,
        catalogHash: 'hash_clean',
        discoveredAt: '2026-11-06T10:00:00Z',
        streams: [],
      }),
    );
    const html = renderEntitiesTab(
      <ConnectionEntitiesSyncTab
        connectionId="conn_new_clean"
        onOpenTrace={() => undefined}
        onProblem={() => undefined}
      />,
      qc,
    );

    expect(html).toContain('Entities');
    expect(html).toContain('Discover Entities...');
    expect(html).toContain('Search Entities');
    expect(html).toContain('Sync From');
    expect(html).toContain('Schedule');
    expect(html).toContain('Status');
    expect(html).not.toContain('stream_alpha');
    expect(html).not.toContain('stream_beta');
  });

  it('keeps table clean upon catalog discovery until user selects discovered streams', () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    qc.setQueryData(ipQueryKeys.syncRuns.streamStates(SEED_TENANT_ID, 'conn_generic_sim'), ok([]));
    qc.setQueryData(
      ipQueryKeys.connections.catalog(SEED_TENANT_ID, 'conn_generic_sim'),
      ok({
        connectionId: 'conn_generic_sim',
        catalogVersion: 1,
        catalogHash: 'hash_gen_123',
        discoveredAt: '2026-11-06T10:00:00Z',
        streams: [
          {
            name: 'stream_beta',
            primaryKey: ['entity_id'],
            cursorField: null,
            supportedSyncModes: ['FULL_REFRESH', 'INCREMENTAL'],
            fields: [
              { name: 'entity_id', dataType: 'STRING', nullable: false, description: null },
              { name: 'attribute_val', dataType: 'STRING', nullable: true, description: null },
            ],
          },
        ],
      }),
    );
    const html = renderEntitiesTab(
      <ConnectionEntitiesSyncTab
        connectionId="conn_generic_sim"
        onOpenTrace={() => undefined}
        onProblem={() => undefined}
      />,
      qc,
    );

    expect(html).not.toContain('UNSYNCED');
    expect(html).toContain('No entities');
    expect(html).toContain('Discover Entities...');
    expect(html).toContain('Search Entities');
  });

  it('renders Virtual Sandbox Entities panel inside ConnectionOverviewTab while keeping ConnectionEntitiesSyncTab focused on discovery', () => {
    const qc = createEntitiesQueryClient();
    const simConnection = {
      ...SEED_CONNECTION,
      appId: UNIVERSAL_SIMULATOR_APP_ID,
      authType: AuthType.API_KEY,
      publicConfig: {
        sandbox_id: SEED_SIMULATOR_SANDBOX_ID,
        seed: 42,
      },
    };
    const overviewHtml = renderEntitiesTab(
      <ConnectionOverviewTab
        connection={simConnection}
        onProblem={() => undefined}
        onDeactivated={() => undefined}
      />,
      qc,
    );
    expect(overviewHtml).toContain('Create Entity');
    expect(overviewHtml).toContain('Virtual Sandbox Entities');
    expect(overviewHtml).toContain(SEED_SIMULATOR_SANDBOX_ID);
    expect(overviewHtml).toContain('orders');
    expect(overviewHtml).toContain('role="region"');
    expect(overviewHtml).toContain('tabindex="0"');

    const entitiesHtml = renderEntitiesTab(
      <ConnectionEntitiesSyncTab
        connectionId={SEED_CONNECTION_ID}
        connection={simConnection}
        onOpenTrace={() => undefined}
        onProblem={() => undefined}
      />,
      qc,
    );

    expect(entitiesHtml).not.toContain('Create Entity');
    expect(entitiesHtml).toContain('Discover Entities');
    expect(entitiesHtml).toContain('Webhook');
    expect(entitiesHtml).toContain('Simulate Push');
  });

  it('renders ActiveConnectionCard as semantic article with Manage Entities action plus per-stream ingress URL helper', () => {
    const qc = createEntitiesQueryClient();
    const html = renderEntitiesTab(
      <ActiveConnectionCard
        connection={SEED_CONNECTION}
        catalogApp={SEED_CATALOG_APPS[0]}
        appIcon={<span>S</span>}
        baseUrl="https://api.soopa.local"
        tenantId={SEED_TENANT_ID}
        onOpenDetail={() => undefined}
        onRequestDelete={() => undefined}
      />,
      qc,
    );

    expect(html).toContain('<article');
    expect(html).toContain('Manage Entities');
    expect(html).not.toContain('Copy Webhook');
    expect(buildIngressWebhookUrl('https://api.soopa.local', 'tenant-1', 'conn-99', 'orders')).toBe(
      'https://api.soopa.local/api/v1/tenants/tenant-1/ip/ingress/conn-99?stream=orders',
    );
  });

  it('activates ActiveConnectionCard keyboard shortcut only when card root is the direct event target', () => {
    const cardTarget = { node: 'article' };
    const nestedButtonTarget = { node: 'button' };

    expect(
      shouldActivateCardOnKeyDown({
        key: 'Enter',
        target: cardTarget,
        currentTarget: cardTarget,
      }),
    ).toBe(true);
    expect(
      shouldActivateCardOnKeyDown({
        key: ' ',
        target: cardTarget,
        currentTarget: cardTarget,
      }),
    ).toBe(true);
    expect(
      shouldActivateCardOnKeyDown({
        key: 'Enter',
        target: nestedButtonTarget,
        currentTarget: cardTarget,
      }),
    ).toBe(false);
    expect(
      shouldActivateCardOnKeyDown({
        key: ' ',
        target: nestedButtonTarget,
        currentTarget: cardTarget,
      }),
    ).toBe(false);
  });

  it('rejects duplicate Virtual Sandbox entity names while permitting edits on the same entity record', () => {
    const existing = [
      { id: 'siment_1', entityName: 'orders' },
      { id: 'siment_2', entityName: 'invoices' },
    ];

    expect(findDuplicateSimulatorEntityError(existing, 'Orders')).toContain(
      'already exists in this Virtual Sandbox',
    );
    expect(findDuplicateSimulatorEntityError(existing, 'orders', 'siment_1')).toBeNull();
    expect(findDuplicateSimulatorEntityError(existing, 'customers')).toBeNull();
  });

  it('surfaces ApiProblem via onProblem when stream schedule persistence fails', async () => {
    const recordedProblems: Array<ApiProblem | null> = [];
    const failureProblem: ApiProblem = {
      code: ApiErrorCode.CONFLICT,
      status: 409,
      message: 'Unable to persist stream schedule.',
    };

    const failedSave = await commitStreamScheduleConfigUpdate({
      connection: SEED_CONNECTION,
      nextSchedules: { orders: '5m' },
      nextSyncFrom: { orders: '24h' },
      mutateUpdate: async () => err(failureProblem),
      onProblem: (problem) => {
        recordedProblems.push(problem);
      },
    });

    expect(failedSave).toBe(false);
    expect(recordedProblems).toEqual([null, failureProblem]);

    const succeededSave = await commitStreamScheduleConfigUpdate({
      connection: SEED_CONNECTION,
      nextSchedules: { orders: '15m' },
      nextSyncFrom: { orders: 'all' },
      mutateUpdate: async (input) =>
        ok({
          ...SEED_CONNECTION,
          publicConfig: input.updatedPublicConfig,
        }),
      onProblem: (problem) => {
        recordedProblems.push(problem);
      },
    });

    expect(succeededSave).toBe(true);
    expect(recordedProblems).toEqual([null, failureProblem, null]);
  });

  it('renders CreateSimulatorEntityForm with shared MonacoCodeEditor instead of raw textarea', () => {
    const qc = createEntitiesQueryClient();
    const html = renderEntitiesTab(
      <CreateSimulatorEntityForm
        sandboxId={SEED_SIMULATOR_SANDBOX_ID}
        onProblem={() => undefined}
        onCancel={() => undefined}
      />,
      qc,
    );

    expect(html).toContain('Entity Name *');
    expect(html).toContain('Entity Blueprint (JSON) *');
    expect(html).toContain('Stream Velocity Mode');
    expect(html).toContain('name="velocity_mode"');
    expect(html).toContain('Upload .json');
    expect(html).toContain('Format');
    expect(html).toContain('aria-labelledby=');
    expect(html.toLowerCase()).toContain('autocorrect="off"');
    expect(html).not.toContain('<textarea');
  });

  it('parses valid simulator JSON blueprints in a single pass while rejecting non-object payloads', () => {
    expect(inferSimulatorEntityNameFromFilename('Customer-Invoices.schema.json')).toBe(
      'customer_invoices',
    );
    expect(parseSimulatorBlueprint('{"order_id":"ORD-1","total":50}')).toEqual({
      ok: true,
      formatted: '{\n  "order_id": "ORD-1",\n  "total": 50\n}',
      parsed: { order_id: 'ORD-1', total: 50 },
    });
    expect(parseSimulatorBlueprint('42').ok).toBe(false);
    expect(parseSimulatorBlueprint('{broken').ok).toBe(false);
  });

  it('enforces authenticated Virtual Sandbox lifecycle across InMemorySimulatorRepository without polluting publicConfig', async () => {
    const harness = createInMemoryIpWorkspaceSeed();
    const sbxRes = await harness.simulator.createSandbox(SEED_TENANT_ID, {
      name: 'Orders Virtual Sandbox',
    });
    expect(sbxRes.ok).toBe(true);
    if (!sbxRes.ok) return;

    const badCheck = await harness.connections.checkConnection(SEED_TENANT_ID, {
      appId: UNIVERSAL_SIMULATOR_APP_ID,
      authType: AuthType.API_KEY,
      publicConfig: { sandbox_id: sbxRes.value.id },
      rawCredentials: { api_key: 'sbx_key_invalid' },
    });
    expect(badCheck.ok && badCheck.value.status).toBe(ConnectionHandshakeStatus.AUTH_FAILED);

    const goodCheck = await harness.connections.checkConnection(SEED_TENANT_ID, {
      appId: UNIVERSAL_SIMULATOR_APP_ID,
      authType: AuthType.API_KEY,
      publicConfig: { sandbox_id: sbxRes.value.id },
      rawCredentials: { api_key: sbxRes.value.apiKey },
    });
    expect(goodCheck.ok && goodCheck.value.status).toBe(ConnectionHandshakeStatus.VERIFIED);

    const connRes = await harness.connections.createConnection(SEED_TENANT_ID, {
      appId: UNIVERSAL_SIMULATOR_APP_ID,
      name: 'Orders Sandbox Connection',
      authType: AuthType.API_KEY,
      publicConfig: { sandbox_id: sbxRes.value.id, seed: 7 },
      rawCredentials: { api_key: sbxRes.value.apiKey },
      endpointForFingerprint: sbxRes.value.id,
    });
    expect(connRes.ok).toBe(true);
    if (!connRes.ok) return;

    const entRes = await harness.simulator.createEntity(SEED_TENANT_ID, sbxRes.value.id, {
      entityName: 'invoices',
      sampleBlueprint: { invoice_id: 'INV-1', amount: 300 },
      primaryKeyField: 'invoice_id',
      cursorField: 'updated_at',
      recordsPerPull: 40,
    });
    expect(entRes.ok).toBe(true);
    if (!entRes.ok) return;

    const updatedEntRes = await harness.simulator.updateEntity(
      SEED_TENANT_ID,
      sbxRes.value.id,
      entRes.value.id,
      { recordsPerPull: 80 },
    );
    expect(updatedEntRes.ok && updatedEntRes.value.version).toBe(2);

    const catalogRes = await harness.connections.discoverCatalog(SEED_TENANT_ID, connRes.value.id);
    expect(catalogRes.ok).toBe(true);
    if (!catalogRes.ok) return;
    expect(catalogRes.value.streams.map((s) => s.name)).toEqual(['invoices']);
    expect('streams' in connRes.value.publicConfig).toBe(false);
  });
});
