import { ok } from '@soopa/ui';
import { RecordingLoggerFake } from '@soopa/ui/testing';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ipQueryKeys } from '../application/query-keys';
import { buildIngressWebhookUrl } from '../domain/connection';
import {
  AuthType,
  ConnectionHandshakeStatus,
  EntitySyncFrom,
  EntitySyncSchedule,
  SyncRunKind,
  UNIVERSAL_SIMULATOR_APP_ID,
} from '../domain/enums';
import {
  ActiveConnectionCard,
  shouldActivateCardOnKeyDown,
} from '../presentation/connections/ActiveConnectionCard';
import {
  ConnectionEntitiesSyncTab,
  reconcileSelectedStreamNames,
} from '../presentation/connections/ConnectionEntitiesSyncTab';
import { ConnectionOverviewTab } from '../presentation/connections/ConnectionOverviewTab';
import {
  CreateSimulatorEntityForm,
  findDuplicateSimulatorEntityError,
  inferSimulatorEntityNameFromFilename,
  parseSimulatorBlueprint,
} from '../presentation/connections/CreateSimulatorEntityModal';
import { resolveConnectionOverviewExtension } from '../presentation/connections/connection-overview-extensions';
import { IpConnectionDetailPage } from '../presentation/connections/IpConnectionDetailPage';
import { SimulatorEntitiesSection } from '../presentation/connections/SimulatorEntitiesSection';
import { SubscribedEntitySchemaPanel } from '../presentation/connections/SubscribedEntitySchemaPanel';
import { IpUIProvider } from '../provider/IpUIProvider';
import {
  createInMemoryIpWorkspaceSeed,
  type InMemoryIpWorkspaceHarness,
  SEED_CATALOG_APPS,
  SEED_CONNECTION,
  SEED_CONNECTION_ENTITY,
  SEED_CONNECTION_ID,
  SEED_SIMULATOR_APP_SPEC,
  SEED_SIMULATOR_ENTITY,
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
    ipQueryKeys.simulator.entities(SEED_TENANT_ID, SEED_CONNECTION_ID),
    ok([SEED_SIMULATOR_ENTITY]),
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
    ipQueryKeys.connections.discoveredStreams(SEED_TENANT_ID, SEED_CONNECTION_ID),
    ok({
      connectionId: SEED_CONNECTION_ID,
      catalogHash: 'hash-init',
      discoveredAt: '2026-11-05T10:00:00Z',
      streams: [],
    }),
  );
  return qc;
}

function renderEntitiesTab(
  node: React.ReactNode,
  queryClient: QueryClient,
  harness: InMemoryIpWorkspaceHarness = createInMemoryIpWorkspaceSeed(),
): string {
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
    qc.setQueryData(ipQueryKeys.connections.entities(SEED_TENANT_ID, 'conn_new_clean'), ok([]));
    qc.setQueryData(
      ipQueryKeys.connections.discoveredStreams(SEED_TENANT_ID, 'conn_new_clean'),
      ok({
        connectionId: 'conn_new_clean',
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
    qc.setQueryData(ipQueryKeys.connections.entities(SEED_TENANT_ID, 'conn_generic_sim'), ok([]));
    qc.setQueryData(
      ipQueryKeys.connections.discoveredStreams(SEED_TENANT_ID, 'conn_generic_sim'),
      ok({
        connectionId: 'conn_generic_sim',
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

  it('isolates Simulate Push strictly onto SimulatorEntitiesSection outside production sync controls', () => {
    const qc = createEntitiesQueryClient();
    const simConnection = {
      ...SEED_CONNECTION,
      appId: UNIVERSAL_SIMULATOR_APP_ID,
      authType: AuthType.NO_AUTH,
      publicConfig: {
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
    expect(overviewHtml).toContain('Connection Details');
    expect(overviewHtml).not.toContain('Create Entity');
    expect(overviewHtml).not.toContain('Simulator Entities');
    expect(overviewHtml).not.toContain('Virtual Sandbox');

    const simulatorSectionHtml = renderEntitiesTab(
      <SimulatorEntitiesSection connectionId={SEED_CONNECTION_ID} onProblem={() => undefined} />,
      qc,
    );
    expect(simulatorSectionHtml).toContain('Simulator Entities');
    expect(simulatorSectionHtml).toContain('Create Entity');
    expect(simulatorSectionHtml).toContain('Push Cadence');
    expect(simulatorSectionHtml).not.toContain('Records per Pull');
    expect(simulatorSectionHtml).toContain('orders');
    expect(simulatorSectionHtml).toContain('Simulate Data');
    expect(simulatorSectionHtml).toContain('Edit');
    expect(simulatorSectionHtml).toContain('Delete');
    expect(simulatorSectionHtml).toContain('role="region"');
    expect(simulatorSectionHtml).toContain('tabindex="0"');

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
    expect(entitiesHtml).not.toContain('>orders<');
    expect(entitiesHtml).toContain('records_alpha');
    expect(entitiesHtml).toContain('Discover Entities...');
    expect(entitiesHtml).not.toContain('<span>Discover Entities</span>');
    expect(entitiesHtml).not.toContain('Webhook');
    expect(entitiesHtml).not.toContain('Simulate Data');
  });

  it('renders ActiveConnectionCard with Copy Webhook button plus readable-prefix ingress URL helper', () => {
    const qc = createEntitiesQueryClient();
    const html = renderEntitiesTab(
      <ActiveConnectionCard
        connection={SEED_CONNECTION}
        catalogApp={SEED_CATALOG_APPS[0]}
        appIcon={<span>S</span>}
        baseUrl="https://api.soopa.local"
        tenantSlug="acme-tenant"
        onOpenDetail={() => undefined}
        onRequestDelete={() => undefined}
      />,
      qc,
    );

    expect(html).toContain('<article');
    expect(html).toContain('Copy Webhook');
    expect(html).toContain('Manage Entities');
    expect(
      buildIngressWebhookUrl(
        'https://api.soopa.local',
        'acme-tenant',
        'universal_simulator',
        'ip_conn_99',
      ),
    ).toBe('https://api.soopa.local/api/v1/webhooks/acme-tenant/universal_simulator/ip_conn_99');
    expect(() =>
      buildIngressWebhookUrl('https://api.soopa.local', '', 'universal_simulator', 'ip_conn_99'),
    ).toThrow('buildIngressWebhookUrl requires non-empty tenantSlug, appId, and connectionId.');
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

  it('rejects duplicate Simulator entity names while permitting edits on the same entity record', () => {
    const existing = [
      { id: 'siment_1', entityName: 'orders' },
      { id: 'siment_2', entityName: 'invoices' },
    ];

    expect(findDuplicateSimulatorEntityError(existing, 'Orders')).toContain(
      'already exists in this Simulator connection',
    );
    expect(findDuplicateSimulatorEntityError(existing, 'orders', 'siment_1')).toBeNull();
    expect(findDuplicateSimulatorEntityError(existing, 'customers')).toBeNull();
  });

  it('rejects custom sync-from updates without an explicit timestamp', async () => {
    const harness = createInMemoryIpWorkspaceSeed();
    const invalidCustomRes = await harness.entities.updateEntity(
      SEED_TENANT_ID,
      SEED_CONNECTION_ID,
      'records_alpha',
      { syncFrom: EntitySyncFrom.CUSTOM },
    );
    expect(invalidCustomRes.ok).toBe(false);
  });

  it('preserves subscribed entity schedules across tab navigation remounts', async () => {
    const harness = createInMemoryIpWorkspaceSeed();

    const subscribedRes = await harness.entities.addEntity(SEED_TENANT_ID, SEED_CONNECTION_ID, {
      streamName: 'customers',
      syncMode: SyncRunKind.INCREMENTAL,
      schedule: EntitySyncSchedule.EVERY_5M,
      syncFrom: EntitySyncFrom.LAST_7D,
      primaryKey: ['customer_id'],
      fields: [{ name: 'customer_id', dataType: 'string', nullable: false, description: null }],
      cursorField: 'updated_at',
    });
    expect(subscribedRes.ok).toBe(true);

    const customWindowRes = await harness.entities.updateEntity(
      SEED_TENANT_ID,
      SEED_CONNECTION_ID,
      'records_alpha',
      {
        schedule: EntitySyncSchedule.HOURLY,
        syncFrom: EntitySyncFrom.CUSTOM,
        syncFromAt: '2026-11-01T00:00:00Z',
      },
    );
    expect(customWindowRes.ok).toBe(true);

    const qc = createEntitiesQueryClient();
    const persistedEntities = await harness.entities.listEntities(
      SEED_TENANT_ID,
      SEED_CONNECTION_ID,
    );
    expect(persistedEntities.ok).toBe(true);
    if (!persistedEntities.ok) return;
    qc.setQueryData(
      ipQueryKeys.connections.entities(SEED_TENANT_ID, SEED_CONNECTION_ID),
      ok(persistedEntities.value),
    );

    const initialEntitiesHtml = renderEntitiesTab(
      <ConnectionEntitiesSyncTab
        connectionId={SEED_CONNECTION_ID}
        connection={SEED_CONNECTION}
        onOpenTrace={() => undefined}
        onProblem={() => undefined}
      />,
      qc,
      harness,
    );
    expect(initialEntitiesHtml).toContain('records_alpha');
    expect(initialEntitiesHtml).toContain('customers');
    expect(initialEntitiesHtml).toContain('Every 5 minutes');
    expect(initialEntitiesHtml).toContain('Last 7 Days');
    expect(initialEntitiesHtml).toContain('2026-11-01');
    expect(initialEntitiesHtml).toContain('Sync Selected (2)');

    const overviewHtmlWhileNavigatedAway = renderEntitiesTab(
      <ConnectionOverviewTab
        connection={SEED_CONNECTION}
        onProblem={() => undefined}
        onDeactivated={() => undefined}
      />,
      qc,
      harness,
    );
    expect(overviewHtmlWhileNavigatedAway).toContain('Connection Details');
    expect(overviewHtmlWhileNavigatedAway).not.toContain('Sync Selected');

    const remountedEntitiesHtml = renderEntitiesTab(
      <ConnectionEntitiesSyncTab
        connectionId={SEED_CONNECTION_ID}
        connection={SEED_CONNECTION}
        onOpenTrace={() => undefined}
        onProblem={() => undefined}
      />,
      qc,
      harness,
    );
    expect(remountedEntitiesHtml).toContain('records_alpha');
    expect(remountedEntitiesHtml).toContain('customers');
    expect(remountedEntitiesHtml).toContain('Every 5 minutes');
    expect(remountedEntitiesHtml).toContain('Last 7 Days');
    expect(remountedEntitiesHtml).toContain('2026-11-01');
    expect(remountedEntitiesHtml).toContain('Sync Selected (2)');
  });

  it('renders CreateSimulatorEntityForm with shared MonacoCodeEditor instead of raw textarea', () => {
    const qc = createEntitiesQueryClient();
    const html = renderEntitiesTab(
      <CreateSimulatorEntityForm
        connectionId={SEED_CONNECTION_ID}
        onProblem={() => undefined}
        onCancel={() => undefined}
      />,
      qc,
    );

    expect(html).toContain('Entity Name *');
    expect(html).toContain('Entity Blueprint (JSON) *');
    expect(html).toContain('Primary Key');
    expect(html).not.toContain('Cursor Field');
    expect(html).toContain('Push Delivery Options');
    expect(html).toContain('Push Emission Mode');
    expect(html).not.toContain('Records per Pull');
    expect(html).toContain('Stream Velocity Mode');
    expect(html).toContain('name="velocity_mode"');
    expect(html).toContain('Upload .json');
    expect(html).toContain('Format');
    expect(html).toContain('aria-labelledby=');
    expect(html.toLowerCase()).toContain('autocorrect="off"');
    expect(html).not.toContain('<textarea');
    expect(html).not.toContain('Gear 1 OLTP records');
    expect(html).not.toContain('Gear 2 columnar batches');
  });

  it('prunes removed Simulator stream names from batch sync selection while auto-selecting newly created streams', () => {
    const initial = new Set(['orders', 'deleted_stream']);
    const validAfterDelete = new Set(['orders', 'invoices']);

    const reconciled = reconcileSelectedStreamNames(initial, validAfterDelete, ['invoices']);
    expect([...reconciled]).toEqual(['orders', 'invoices']);

    const unchanged = reconcileSelectedStreamNames(reconciled, validAfterDelete, []);
    expect(unchanged).toBe(reconciled);
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

  it('scopes Simulator entity lifecycle directly to connectionId without polluting publicConfig', async () => {
    const harness = createInMemoryIpWorkspaceSeed();

    const checkRes = await harness.connections.checkConnection(SEED_TENANT_ID, {
      appId: UNIVERSAL_SIMULATOR_APP_ID,
      authType: AuthType.NO_AUTH,
      publicConfig: { seed: 7 },
      rawCredentials: {},
    });
    expect(checkRes.ok && checkRes.value.status).toBe(ConnectionHandshakeStatus.VERIFIED);

    const connRes = await harness.connections.createConnection(SEED_TENANT_ID, {
      appId: UNIVERSAL_SIMULATOR_APP_ID,
      name: 'Orders Simulator Connection',
      authType: AuthType.NO_AUTH,
      publicConfig: { seed: 7 },
      rawCredentials: {},
      endpointForFingerprint: 'Orders Simulator Connection',
    });
    expect(connRes.ok).toBe(true);
    if (!connRes.ok) return;

    const entRes = await harness.simulator.createEntity(SEED_TENANT_ID, connRes.value.id, {
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
      connRes.value.id,
      entRes.value.id,
      { recordsPerPull: 80 },
    );
    expect(updatedEntRes.ok && updatedEntRes.value.version).toBe(2);

    const catalogRes = await harness.connections.discoverCatalog(SEED_TENANT_ID, connRes.value.id);
    expect(catalogRes.ok).toBe(true);
    if (!catalogRes.ok) return;
    expect(catalogRes.value.streams.map((s) => s.name)).toEqual(['invoices']);
    expect('streams' in connRes.value.publicConfig).toBe(false);
    expect('sandbox_id' in connRes.value.publicConfig).toBe(false);
  });

  it('renders SimulatorEntitiesSection inside Connection tab exclusively for NO_AUTH simulator connections without adding extra tabs', () => {
    const qc = createEntitiesQueryClient();
    const freshSimConnection = {
      ...SEED_CONNECTION,
      id: 'ip_conn_orders_sim_fresh',
      name: 'Order Simulator',
      appId: UNIVERSAL_SIMULATOR_APP_ID,
      authType: AuthType.NO_AUTH,
      publicConfig: {
        seed: 42,
        records_per_pull: 25,
      },
    };
    qc.setQueryData(
      ipQueryKeys.connections.detail(SEED_TENANT_ID, SEED_CONNECTION.id),
      ok(SEED_CONNECTION),
    );
    qc.setQueryData(
      ipQueryKeys.connections.detail(SEED_TENANT_ID, freshSimConnection.id),
      ok(freshSimConnection),
    );
    qc.setQueryData(ipQueryKeys.simulator.entities(SEED_TENANT_ID, freshSimConnection.id), ok([]));

    const standardDetailHtml = renderEntitiesTab(
      <IpConnectionDetailPage connectionId={SEED_CONNECTION.id} />,
      qc,
    );
    expect(standardDetailHtml).toContain('Connection');
    expect(standardDetailHtml).toContain('Entities');
    expect(standardDetailHtml).not.toContain('Simulator Entities');

    const simulatorDetailHtml = renderEntitiesTab(
      <IpConnectionDetailPage connectionId={freshSimConnection.id} />,
      qc,
    );
    expect(simulatorDetailHtml.match(/role="tab"/g)?.length).toBe(2);
    expect(simulatorDetailHtml).toContain('Connection Details');
    expect(simulatorDetailHtml).toContain('Simulator Entities');
    expect(simulatorDetailHtml).toContain('Create Entity');
    expect(simulatorDetailHtml).toContain('No entities');
    expect(simulatorDetailHtml).not.toContain('Configured directly on this Simulator connection');
    expect(simulatorDetailHtml).not.toContain('No entities configured in this Simulator yet');
    expect(simulatorDetailHtml).not.toContain('Virtual Sandbox');
  });

  it('keeps ConnectionEntitiesSyncTab clean for newly created Simulator entities until discovered via single combobox', async () => {
    const harness = createInMemoryIpWorkspaceSeed();
    const createdConnRes = await harness.connections.createConnection(SEED_TENANT_ID, {
      appId: UNIVERSAL_SIMULATOR_APP_ID,
      name: 'Order Simulator',
      authType: AuthType.NO_AUTH,
      publicConfig: { seed: 42, records_per_pull: 25 },
      rawCredentials: {},
    });
    expect(createdConnRes.ok).toBe(true);
    if (!createdConnRes.ok) return;

    const entityRes = await harness.simulator.createEntity(
      SEED_TENANT_ID,
      createdConnRes.value.id,
      {
        entityName: 'invoices',
        sampleBlueprint: { invoice_id: 'INV-1001', amount: 42.5 },
        primaryKeyField: 'invoice_id',
        cursorField: 'updated_at',
        recordsPerPull: 25,
      },
    );
    expect(entityRes.ok).toBe(true);
    if (!entityRes.ok) return;

    const discoverRes = await harness.connections.discoverCatalog(
      SEED_TENANT_ID,
      createdConnRes.value.id,
    );
    expect(discoverRes.ok).toBe(true);
    if (!discoverRes.ok) return;
    expect(discoverRes.value.streams.map((s) => s.name)).toEqual(['invoices']);

    const qc = createEntitiesQueryClient();
    qc.setQueryData(
      ipQueryKeys.simulator.entities(SEED_TENANT_ID, createdConnRes.value.id),
      ok([entityRes.value]),
    );
    qc.setQueryData(
      ipQueryKeys.connections.discoveredStreams(SEED_TENANT_ID, createdConnRes.value.id),
      ok(discoverRes.value),
    );
    qc.setQueryData(
      ipQueryKeys.connections.entities(SEED_TENANT_ID, createdConnRes.value.id),
      ok([]),
    );
    qc.setQueryData(ipQueryKeys.syncRuns.list(SEED_TENANT_ID, createdConnRes.value.id, 40), ok([]));

    const simulatorSectionHtml = renderEntitiesTab(
      <SimulatorEntitiesSection
        connectionId={createdConnRes.value.id}
        onProblem={() => undefined}
      />,
      qc,
    );
    expect(simulatorSectionHtml).toContain('invoices');

    const entitiesHtml = renderEntitiesTab(
      <ConnectionEntitiesSyncTab
        connectionId={createdConnRes.value.id}
        connection={createdConnRes.value}
        onOpenTrace={() => undefined}
        onProblem={() => undefined}
      />,
      qc,
    );
    expect(entitiesHtml).not.toContain('invoices');
    expect(entitiesHtml).toContain('No entities');
    expect(entitiesHtml).toContain('Sync Selected (0)');
    expect(entitiesHtml).toContain('Discover Entities...');
    expect(entitiesHtml).toContain('role="combobox"');
    expect(entitiesHtml).not.toContain('<span>Discover Entities</span>');
  });

  it('returns empty discovered catalog without error when simulator connection has zero entities configured', async () => {
    const harness = createInMemoryIpWorkspaceSeed();
    const createdConnRes = await harness.connections.createConnection(SEED_TENANT_ID, {
      appId: UNIVERSAL_SIMULATOR_APP_ID,
      name: 'Empty Order Simulator',
      authType: AuthType.NO_AUTH,
      publicConfig: { seed: 42, records_per_pull: 25 },
      rawCredentials: {},
    });
    expect(createdConnRes.ok).toBe(true);
    if (!createdConnRes.ok) return;

    const discoverRes = await harness.connections.discoverCatalog(
      SEED_TENANT_ID,
      createdConnRes.value.id,
    );
    expect(discoverRes.ok).toBe(true);
    if (!discoverRes.ok) return;
    expect(discoverRes.value.streams).toEqual([]);
  });

  it('renders accessible schema disclosure buttons plus design-system SubscribedEntitySchemaPanel', () => {
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

    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('aria-label="records_alpha schema fields"');
    expect(html).not.toContain('data-radix-popper-content-wrapper');

    const schemaHtml = renderEntitiesTab(
      <SubscribedEntitySchemaPanel
        primaryKey={['record_id']}
        fields={[{ name: 'record_id', dataType: 'string', nullable: false, description: null }]}
      />,
      qc,
    );
    expect(schemaHtml).toContain('data-slot="table"');
    expect(schemaHtml).toContain('Primary Key: record_id');
    expect(schemaHtml).toContain('scope="col"');

    expect(resolveConnectionOverviewExtension('acme_source')).toBeNull();
    expect(resolveConnectionOverviewExtension(UNIVERSAL_SIMULATOR_APP_ID)).not.toBeNull();
  });

  it('renders inline entity-centric data inspection panel when entity row is expanded', () => {
    const qc = createEntitiesQueryClient();
    qc.setQueryData(
      ipQueryKeys.records.normalized(SEED_TENANT_ID, {
        connectionId: SEED_CONNECTION_ID,
        limit: 100,
      }),
      ok([
        {
          id: 'norm-entity-1',
          tenantId: SEED_TENANT_ID,
          traceId: 'tr-1',
          connectionId: SEED_CONNECTION_ID,
          canonicalType: 'records_alpha',
          sourceId: 'SRC-alpha-1',
          canonicalData: { record_id: 'SRC-alpha-1', value_num: 120 },
          normalizedAt: '2026-11-05T10:00:00Z',
        },
      ]),
    );

    const html = renderEntitiesTab(
      <ConnectionEntitiesSyncTab
        connectionId={SEED_CONNECTION_ID}
        connection={SEED_CONNECTION}
        initialExpandedEntity="records_alpha"
        onOpenTrace={() => undefined}
        onProblem={() => undefined}
      />,
      qc,
    );

    expect(html).toContain('Records Alpha');
    expect(html).toContain('1 record');
    expect(html).toContain('role="region"');
    expect(html).toContain('aria-label="records_alpha records table"');
    expect(html).toContain('Record ID');
    expect(html).toContain('Value Num');
    expect(html).toContain('PK');
    // Verifies no confusing engineering tabs leak into user view
    expect(html).not.toContain('L3: Normalized Canonical');
    expect(html).not.toContain('GEM: Identity Map');
    expect(html).not.toContain('Current View: Customer Support (Full Diagnostic)');
  });
});
