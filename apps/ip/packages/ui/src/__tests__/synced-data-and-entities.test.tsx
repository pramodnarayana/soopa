import { FetchHttpClientAdapter, ok } from '@soopa/ui';
import { RecordingLoggerFake } from '@soopa/ui/testing';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { HttpRecordRepository } from '../adapters/http/repositories/http-record.repository';
import { ipQueryKeys } from '../application/query-keys';
import { PipelineLayer } from '../domain/enums';
import { ConnectionEntitiesSyncTab } from '../presentation/connections/ConnectionDetailTabs';
import { SyncedDataInspectionPanel } from '../presentation/records/SyncedDataInspectionPanel';
import { TraceWaterfallStageContent } from '../presentation/traces/TraceWaterfallStages';
import { IpUIProvider } from '../provider/IpUIProvider';
import {
  createInMemoryIpWorkspaceSeed,
  SEED_CATALOG_APPS,
  SEED_CONNECTION,
  SEED_CONNECTION_ID,
  SEED_STREAM_STATE,
  SEED_SYNC_RUN,
  SEED_TENANT_ID,
  SEED_TRACE,
} from '../testing';

interface RecordedCall {
  readonly method: string;
  readonly url: string;
}

function createRouteFetch(routes: Readonly<Record<string, unknown>>): {
  readonly fetchImpl: typeof fetch;
  readonly calls: RecordedCall[];
} {
  const calls: RecordedCall[] = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    const method = init?.method ?? 'GET';
    const url =
      typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const parsedUrl = new URL(url);
    const key = `${method} ${parsedUrl.pathname}`;
    calls.push({ method, url });
    const payload = routes[key];
    if (payload === undefined) {
      return new Response(JSON.stringify({ detail: `Unmapped ${key}` }), { status: 404 });
    }
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  return { fetchImpl, calls };
}

function createRecordQueryClient(): QueryClient {
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
    ipQueryKeys.records.normalized(SEED_TENANT_ID, {
      connectionId: SEED_CONNECTION_ID,
      limit: 100,
    }),
    ok([
      {
        id: 'norm-1',
        tenantId: SEED_TENANT_ID,
        traceId: 'tr-1',
        connectionId: SEED_CONNECTION_ID,
        canonicalType: 'CANONICAL_TYPE_A',
        sourceId: 'SRC-1001',
        canonicalData: { serial: 'SRC-1001', model: 'Standard-Model', vendor: 'Acme' },
        normalizedAt: '2026-11-05T10:00:00Z',
      },
    ]),
  );
  qc.setQueryData(
    ipQueryKeys.records.gem(SEED_TENANT_ID, { sourceConnectionId: SEED_CONNECTION_ID, limit: 100 }),
    ok([
      {
        id: 'gem-1',
        tenantId: SEED_TENANT_ID,
        traceId: 'tr-1',
        entityDomain: 'domain_core',
        canonicalId: 'GEM-ENTITY-999',
        sourceConnectionId: SEED_CONNECTION_ID,
        sourceEntityId: 'src-entity-1',
        destConnectionId: null,
        destEntityId: null,
        createdAt: '2026-11-05T10:00:00Z',
      },
    ]),
  );
  qc.setQueryData(
    ipQueryKeys.records.replica(SEED_TENANT_ID, { connectionId: SEED_CONNECTION_ID, limit: 100 }),
    ok([
      {
        id: 'rep-1',
        tenantId: SEED_TENANT_ID,
        traceId: 'tr-1',
        connectionId: SEED_CONNECTION_ID,
        stream: 'stream_alpha',
        recordKey: 'src-1',
        primaryKeyValues: ['src-1'],
        cursorValue: null,
        cursorKind: null,
        data: { raw_payload: 'A100' },
        dataHash: 'sha256-abc',
        version: 1,
        generationId: 1,
        lastSeenGeneration: 1,
        firstSeenAt: '2026-11-05T09:59:00Z',
        extractedAt: '2026-11-05T09:59:00Z',
        updatedAt: '2026-11-05T09:59:00Z',
        deletedAt: null,
        sourceInboundRecordId: 'inb-1',
      },
    ]),
  );
  qc.setQueryData(
    ipQueryKeys.records.inbound(SEED_TENANT_ID, { limit: 100 }),
    ok([
      {
        id: 'inb-1',
        tenantId: SEED_TENANT_ID,
        traceId: 'tr-1',
        connectionId: SEED_CONNECTION_ID,
        appId: 'generic_connector',
        streamName: 'stream_alpha',
        ingestionMode: 'BATCH',
        syncRunId: null,
        generationId: 1,
        externalEventId: null,
        requestHeaders: { 'content-type': 'application/json' },
        requestBody: { batch: [] },
        requestS3Key: null,
        requestSizeBytes: 4096,
        requestSha256: 'sha256-req-1',
        responseStatusCode: 200,
        responseHeaders: {},
        responseBody: { status: 'ok' },
        responseS3Key: null,
        durationMs: 45,
        receivedAt: '2026-11-05T09:58:00Z',
      },
    ]),
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

function renderWithRole(
  node: React.ReactNode,
  userRole: 'support' | 'customer',
  queryClient: QueryClient,
): string {
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
        defaultUserRole={userRole}
      >
        {node}
      </IpUIProvider>
    </QueryClientProvider>,
  );
}

describe('Entities & Sync Control Plane & SyncedDataInspectionPanel (RBAC & Decoupled Architecture)', () => {
  it('renders ConnectionEntitiesSyncTab with multi-select entity table and sync triggers', () => {
    const qc = createRecordQueryClient();
    const html = renderWithRole(
      <ConnectionEntitiesSyncTab
        connectionId={SEED_CONNECTION_ID}
        connection={SEED_CONNECTION}
        onOpenTrace={() => undefined}
        onProblem={() => undefined}
      />,
      'support',
      qc,
    );

    // Entity table elements: single Discover entities dropdown, Search, Sync From, and per-entity Schedule controls
    expect(html).toContain('Entities');
    expect(html).toContain('Discover Entities...');
    expect(html).toContain('Search Entities');
    expect(html).toContain('Sync From');
    expect(html).toContain('Schedule');
    expect(html).toContain('Status');
    expect(html).toContain('Actions');
    expect(html).toContain('meter_reads');
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
    const html = renderWithRole(
      <ConnectionEntitiesSyncTab
        connectionId="conn_new_clean"
        onOpenTrace={() => undefined}
        onProblem={() => undefined}
      />,
      'support',
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

  it('keeps table clean upon catalog discovery and populates SearchableSelect for on-demand user selection', () => {
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
    const html = renderWithRole(
      <ConnectionEntitiesSyncTab
        connectionId="conn_generic_sim"
        onOpenTrace={() => undefined}
        onProblem={() => undefined}
      />,
      'support',
      qc,
    );

    // Discovered streams do NOT automatically pollute the table with rows
    expect(html).not.toContain('UNSYNCED');
    expect(html).toContain('No entities');

    // Single unified Discover entities dropdown is ready for user selection
    expect(html).toContain('Discover Entities...');
    expect(html).toContain('Search Entities');
  });

  it('enforces RBAC visibility in SyncedDataInspectionPanel: Customer Support sees L1–L3 + GEM', () => {
    const qc = createRecordQueryClient();
    const html = renderWithRole(
      <SyncedDataInspectionPanel connectionId={SEED_CONNECTION_ID} onOpenTrace={() => undefined} />,
      'support',
      qc,
    );

    // Support role sees all 5 tabs
    expect(html).toContain('L3: Normalized Canonical');
    expect(html).toContain('GEM: Identity Map');
    expect(html).toContain('L2: Staging Replica');
    expect(html).toContain('L1: Raw Wire Inbound');
    expect(html).toContain('Activity &amp; Traces');
    expect(html).toContain('Customer Support (Full Diagnostic)');
    // Permanent table headers must be visible
    expect(html).toContain('Canonical Entity');
    expect(html).toContain('Source Identifier');
    expect(html).toContain('Normalized At');
    expect(html).toContain('Payload');
  });

  it('renders permanent TableHeader in SyncedDataInspectionPanel even when zero canonical records exist', () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    qc.setQueryData(
      ipQueryKeys.records.normalized(SEED_TENANT_ID, { connectionId: 'conn_empty', limit: 100 }),
      ok([]),
    );
    const html = renderWithRole(
      <SyncedDataInspectionPanel connectionId="conn_empty" onOpenTrace={() => undefined} />,
      'support',
      qc,
    );

    expect(html).toContain('Canonical Entity');
    expect(html).toContain('Source Identifier');
    expect(html).toContain('Normalized At');
    expect(html).toContain('Payload');
    expect(html).toContain(
      'No normalized canonical records found. Trigger a sync to populate this table.',
    );
  });

  it('enforces RBAC visibility in SyncedDataInspectionPanel: Customer role HIDES L1 and L2 tabs', () => {
    const qc = createRecordQueryClient();
    const html = renderWithRole(
      <SyncedDataInspectionPanel connectionId={SEED_CONNECTION_ID} onOpenTrace={() => undefined} />,
      'customer',
      qc,
    );

    // Customer role sees L3, GEM, and Traces
    expect(html).toContain('L3: Normalized Canonical');
    expect(html).toContain('GEM: Identity Map');
    expect(html).toContain('Activity &amp; Traces');
    expect(html).toContain('Customer (Restricted)');

    // Customer role MUST NEVER see L1 or L2 tabs
    expect(html).not.toContain('L2: Staging Replica');
    expect(html).not.toContain('L1: Raw Wire Inbound');
  });

  it('enforces restricted diagnostic card in TraceWaterfallStageContent when userRole is customer', () => {
    const qc = createRecordQueryClient();

    // Customer role attempting to view L1
    const l1Html = renderWithRole(
      <TraceWaterfallStageContent
        activeLayer={PipelineLayer.L1_INGEST}
        trace={SEED_TRACE}
        hasUnhydratedS3={false}
        onHydrateS3={() => undefined}
        onOpenStitches={() => undefined}
      />,
      'customer',
      qc,
    );
    expect(l1Html).toContain('Layer 1: Raw Inbound Wire Capture is Restricted');
    expect(l1Html).toContain('records:raw:read');

    // Customer role attempting to view L2
    const l2Html = renderWithRole(
      <TraceWaterfallStageContent
        activeLayer={PipelineLayer.L2_REPLICA}
        trace={SEED_TRACE}
        hasUnhydratedS3={false}
        onHydrateS3={() => undefined}
        onOpenStitches={() => undefined}
      />,
      'customer',
      qc,
    );
    expect(l2Html).toContain('Layer 2: Universal Replica Staging is Restricted');
    expect(l2Html).toContain('records:raw:read');

    // Customer Support role viewing L1 and L2
    const supportL1Html = renderWithRole(
      <TraceWaterfallStageContent
        activeLayer={PipelineLayer.L1_INGEST}
        trace={SEED_TRACE}
        hasUnhydratedS3={false}
        onHydrateS3={() => undefined}
        onOpenStitches={() => undefined}
      />,
      'support',
      qc,
    );
    expect(supportL1Html).toContain('L1 Raw Wire Capture');

    const supportL2Html = renderWithRole(
      <TraceWaterfallStageContent
        activeLayer={PipelineLayer.L2_REPLICA}
        trace={SEED_TRACE}
        hasUnhydratedS3={false}
        onHydrateS3={() => undefined}
        onOpenStitches={() => undefined}
      />,
      'support',
      qc,
    );
    expect(supportL2Html).toContain('meter_reads');
    expect(supportL2Html).toContain('Generation #1');
  });

  it('HttpRecordRepository correctly calls backend endpoints with tenant and query params', async () => {
    const logger = new RecordingLoggerFake();
    const { fetchImpl, calls } = createRouteFetch({
      'GET /api/v1/tenants/ten_01/ip/records/normalized': [
        {
          id: 'n-1',
          tenant_id: 'ten_01',
          trace_id: 'tr-1',
          connection_id: 'conn-1',
          canonical_type: 'CANONICAL_TYPE_A',
          source_id: 'SRC-1',
          canonical_data: { key: 'val' },
          normalized_at: '2026-11-05T10:00:00Z',
        },
      ],
      'GET /api/v1/tenants/ten_01/ip/records/gem': [
        {
          id: 'g-1',
          tenant_id: 'ten_01',
          trace_id: 'tr-1',
          entity_domain: 'domain_core',
          canonical_id: 'GEM-1',
          source_connection_id: 'conn-1',
          source_entity_id: 'src-1',
          created_at: '2026-11-05T10:00:00Z',
        },
      ],
      'GET /api/v1/tenants/ten_01/ip/records/replica': [
        {
          id: 'rep-1',
          tenant_id: 'ten_01',
          trace_id: 'tr-1',
          connection_id: 'conn-1',
          stream: 'stream_alpha',
          record_key: 'src-1',
          data: {},
          data_hash: 'sha-rep',
          version: 1,
          generation_id: 1,
          last_seen_generation: 1,
          first_seen_at: '2026-11-05T10:00:00Z',
          extracted_at: '2026-11-05T10:00:00Z',
          updated_at: '2026-11-05T10:00:00Z',
          source_inbound_record_id: 'in-1',
        },
      ],
      'GET /api/v1/tenants/ten_01/ip/records/inbound': [
        {
          id: 'in-1',
          tenant_id: 'ten_01',
          trace_id: 'tr-1',
          connection_id: 'conn-1',
          app_id: 'generic_connector',
          stream_name: 'stream_alpha',
          ingestion_mode: 'BATCH',
          request_size_bytes: 128,
          request_sha256: 'sha-req',
          received_at: '2026-11-05T10:00:00Z',
        },
      ],
    });

    const httpClient = new FetchHttpClientAdapter({
      baseUrl: 'https://api.soopa.local',
      fetchImpl,
      logger,
    });
    const repo = new HttpRecordRepository(httpClient, logger);

    const normRes = await repo.listNormalizedRecords('ten_01', {
      connectionId: 'conn-1',
      canonicalType: 'CANONICAL_TYPE_A',
      limit: 25,
      offset: 5,
    });
    expect(normRes.ok).toBe(true);
    if (normRes.ok) {
      expect(normRes.value.length).toBe(1);
      expect(normRes.value[0]?.sourceId).toBe('SRC-1');
    }

    const gemRes = await repo.listGemRecords('ten_01', {
      entityDomain: 'domain_core',
      sourceConnectionId: 'conn-1',
      limit: 20,
      offset: 10,
    });
    expect(gemRes.ok).toBe(true);
    if (gemRes.ok) {
      expect(gemRes.value.length).toBe(1);
      expect(gemRes.value[0]?.canonicalId).toBe('GEM-1');
    }

    const repRes = await repo.listReplicaRecords('ten_01', {
      connectionId: 'conn-1',
      stream: 'stream_alpha',
      limit: 15,
      offset: 2,
    });
    expect(repRes.ok).toBe(true);
    if (repRes.ok) {
      expect(repRes.value.length).toBe(1);
      expect(repRes.value[0]?.stream).toBe('stream_alpha');
    }

    const inbRes = await repo.listInboundRecords('ten_01', {
      connectionId: 'conn-1',
      streamName: 'stream_alpha',
      hydratePayloads: true,
      limit: 30,
      offset: 4,
    });
    expect(inbRes.ok).toBe(true);
    if (inbRes.ok) {
      expect(inbRes.value.length).toBe(1);
      expect(inbRes.value[0]?.appId).toBe('generic_connector');
    }

    expect(calls.length).toBe(4);

    const normUrl = new URL(calls[0]!.url);
    expect(normUrl.pathname).toBe('/api/v1/tenants/ten_01/ip/records/normalized');
    expect(normUrl.searchParams.get('connection_id')).toBe('conn-1');
    expect(normUrl.searchParams.get('canonical_type')).toBe('CANONICAL_TYPE_A');
    expect(normUrl.searchParams.get('limit')).toBe('25');
    expect(normUrl.searchParams.get('offset')).toBe('5');

    const gemUrl = new URL(calls[1]!.url);
    expect(gemUrl.pathname).toBe('/api/v1/tenants/ten_01/ip/records/gem');
    expect(gemUrl.searchParams.get('source_connection_id')).toBe('conn-1');
    expect(gemUrl.searchParams.get('entity_domain')).toBe('domain_core');
    expect(gemUrl.searchParams.get('limit')).toBe('20');
    expect(gemUrl.searchParams.get('offset')).toBe('10');

    const repUrl = new URL(calls[2]!.url);
    expect(repUrl.pathname).toBe('/api/v1/tenants/ten_01/ip/records/replica');
    expect(repUrl.searchParams.get('connection_id')).toBe('conn-1');
    expect(repUrl.searchParams.get('stream')).toBe('stream_alpha');
    expect(repUrl.searchParams.get('limit')).toBe('15');
    expect(repUrl.searchParams.get('offset')).toBe('2');

    const inbUrl = new URL(calls[3]!.url);
    expect(inbUrl.pathname).toBe('/api/v1/tenants/ten_01/ip/records/inbound');
    expect(inbUrl.searchParams.get('connection_id')).toBe('conn-1');
    expect(inbUrl.searchParams.get('stream_name')).toBe('stream_alpha');
    expect(inbUrl.searchParams.get('hydrate_payloads')).toBe('true');
    expect(inbUrl.searchParams.get('limit')).toBe('30');
    expect(inbUrl.searchParams.get('offset')).toBe('4');
  });
});
