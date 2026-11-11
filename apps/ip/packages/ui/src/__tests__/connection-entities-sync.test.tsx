import { ok } from '@soopa/ui';
import { RecordingLoggerFake } from '@soopa/ui/testing';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ipQueryKeys } from '../application/query-keys';
import { buildIngressWebhookUrl } from '../domain/connection';
import { UNIVERSAL_SIMULATOR_APP_ID } from '../domain/enums';
import { ActiveConnectionCard } from '../presentation/connections/ActiveConnectionCard';
import {
  ConnectionEntitiesSyncTab,
  ConnectionOverviewTab,
} from '../presentation/connections/ConnectionDetailTabs';
import {
  CreateSimulatorEntityForm,
  inferSimulatorEntityNameFromFilename,
  parseSimulatorBlueprint,
} from '../presentation/connections/CreateSimulatorEntityModal';
import { IpUIProvider } from '../provider/IpUIProvider';
import {
  createInMemoryIpWorkspaceSeed,
  SEED_CATALOG_APPS,
  SEED_CONNECTION,
  SEED_CONNECTION_ID,
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

  it('renders Create Entity action inside ConnectionOverviewTab while keeping ConnectionEntitiesSyncTab focused on discovery', () => {
    const qc = createEntitiesQueryClient();
    const simConnection = {
      ...SEED_CONNECTION,
      appId: UNIVERSAL_SIMULATOR_APP_ID,
      publicConfig: {
        streams: {
          orders: {
            sample_json: { order_id: 'ORD-1001', total: 120.5 },
          },
        },
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

  it('renders ActiveConnectionCard with Copy Webhook action plus deterministic ingress URL helper', () => {
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

    expect(html).toContain('Copy Webhook');
    expect(buildIngressWebhookUrl('https://api.soopa.local', 'tenant-1', 'conn-99', 'orders')).toBe(
      'https://api.soopa.local/api/v1/tenants/tenant-1/ip/ingress/conn-99?stream=orders',
    );
  });

  it('renders CreateSimulatorEntityForm with shared MonacoCodeEditor instead of raw textarea', () => {
    const qc = createEntitiesQueryClient();
    const simConnection = {
      ...SEED_CONNECTION,
      appId: UNIVERSAL_SIMULATOR_APP_ID,
    };
    const html = renderEntitiesTab(
      <CreateSimulatorEntityForm
        connection={simConnection}
        onProblem={() => undefined}
        onCancel={() => undefined}
      />,
      qc,
    );

    expect(html).toContain('Entity Name *');
    expect(html).toContain('Entity Blueprint (JSON) *');
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
});
