import { ok } from '@soopa/ui';
import { RecordingLoggerFake } from '@soopa/ui/testing';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ipQueryKeys } from '../application/query-keys';
import { ConnectionEntitiesSyncTab } from '../presentation/connections/ConnectionDetailTabs';
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
});
