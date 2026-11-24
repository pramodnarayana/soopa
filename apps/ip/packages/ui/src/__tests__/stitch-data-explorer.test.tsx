import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { StitchNodeKind } from '../domain/enums';
import { isTransactionalStitch, type Stitch, type StitchDefinition } from '../domain/stitch';
import { StitchDetailDataExplorer } from '../presentation/stitches/StitchDetailDataExplorer';
import {
  IpWorkspaceContext,
  type IpWorkspaceContextValue,
} from '../provider/IpRepositoriesContext';

function createMockStitch(
  overrides: Partial<Stitch> & Pick<Stitch, 'id' | 'workflowId' | 'canonicalEventType'>,
): Stitch {
  return {
    tenantId: 'tenant_alpha',
    name: 'Mock Stitch',
    workflowVersion: 1,
    isTrigger: true,
    conditionEventKey: null,
    idempotencyKeyField: 'id',
    concurrencyKeyField: null,
    resourceHintField: null,
    mappingSpecId: null,
    isActive: true,
    ...overrides,
  };
}

describe('StitchDetailDataExplorer Tab Order with Conditional GEM', () => {
  function createMockWorkspaceContext(): IpWorkspaceContextValue {
    const mockLogger = {
      info: () => {},
      warn: () => {},
      error: () => {},
      debug: () => {},
      bind: () => mockLogger,
    };

    return {
      tenantId: 'tenant_alpha',
      tenantSlug: 'alpha',
      userRole: 'support',
      repositories: {
        catalog: {} as any,
        connections: {} as any,
        entities: {} as any,
        syncRuns: {} as any,
        transformations: {} as any,
        mappingSpecs: {} as any,
        stitches: {} as any,
        records: {
          getNormalizedRecords: async () => [],
          getGemRecords: async () => [],
          getReplicaRecords: async () => [],
          getInboundRecords: async () => [],
          listOutboundRecords: async () => [
            {
              id: 'out_rec_001',
              tenantId: 'tenant_alpha',
              connectionId: 'conn_sap',
              destinationApp: 'SAP_S4HANA',
              streamName: 'invoices',
              operation: 'POST',
              targetUrl: 'https://sap.internal/api/invoices',
              statusCode: 503,
              isSuccess: false,
              failureCategory: 'TRANSIENT_5XX',
              errorMessage: '503 Service Unavailable: SAP gateway under maintenance',
              retryAfterSeconds: 30,
              latencyMs: 1420,
              payloadSize: 8192,
              sentAt: '2026-11-23T10:00:00Z',
              traceId: 'tr_01934abc_def123',
              payload: { invoiceId: 'INV-99882', amountDue: 450.2 },
            },
          ],
        } as any,
        traces: {
          replay: async () => ({ ok: true, value: { newTraceId: 'tr_child_999' } }),
        } as any,
        intervals: {} as any,
        simulator: {} as any,
      },
      navigation: {
        toCommandCenter: () => {},
        toTraces: () => {},
        toTraceDetail: () => {},
        toConnections: () => {},
        toConnectionDetail: () => {},
        toTransformations: () => {},
        toStitches: () => {},
        toStitchDefinition: () => {},
        toStitchRun: () => {},
      },
      logger: mockLogger,
      openCommandPalette: () => {},
    };
  }

  describe('Transactional Stitch Detection', () => {
    it('omits GEM for high-throughput streaming pipelines', () => {
      const streamingStitch = createMockStitch({
        id: 'stch_bulk_historical_extraction',
        name: 'Bulk Historical Extraction',
        workflowId: 'platform.bulk_historical_extraction_stitch',
        canonicalEventType: 'command.historical_extract_requests',
        mappingSpecId: null,
      });

      const streamingDefinition: StitchDefinition = {
        workflowId: 'platform.bulk_historical_extraction_stitch',
        version: 1,
        defaultPriority: 'BULK',
        description: 'Multi-stream time-series directly to Kafka',
        nodes: [
          {
            nodeKey: 'publish_records_to_kafka',
            kind: StitchNodeKind.TASK,
            stepType: 'kafka.publish_intervals',
            parents: [],
            edgeCondition: 'ON_SUCCESS',
            effectPolicy: 'IDEMPOTENT_EFFECT',
            waitEventKey: null,
            queueName: 'default',
          },
        ],
      };

      expect(isTransactionalStitch(streamingStitch, streamingDefinition)).toBe(false);
    });

    it('enables GEM for transactional ERP sync workflows', () => {
      const erpStitch = createMockStitch({
        id: 'stch_invoice_erp_sync',
        name: 'Invoice Ledger ERP Sync',
        workflowId: 'finance.ledger_erp_sync_stitch',
        canonicalEventType: 'finance.invoice.erp.sync',
        mappingSpecId: 'spec_erp_billing',
      });

      const erpDefinition: StitchDefinition = {
        workflowId: 'finance.ledger_erp_sync_stitch',
        version: 1,
        defaultPriority: 'BULK',
        description: 'Transactional ERP billing write-back',
        nodes: [
          {
            nodeKey: 'dispatch_sap_erp',
            kind: StitchNodeKind.TASK,
            stepType: 'http.post_erp',
            parents: [],
            edgeCondition: 'ON_SUCCESS',
            effectPolicy: 'TRANSACTIONAL',
            waitEventKey: null,
            queueName: 'default',
          },
        ],
      };

      expect(isTransactionalStitch(erpStitch, erpDefinition)).toBe(true);
      expect(isTransactionalStitch(erpStitch, null)).toBe(true);
      expect(isTransactionalStitch(null, erpDefinition)).toBe(true);
    });
  });

  describe('UI Tab Order Rendering Invariants', () => {
    it('renders tabs in strict sequence omitting GEM for streaming', () => {
      const streamingStitch = createMockStitch({
        id: 'stch_bulk_historical_extraction',
        name: 'Bulk Historical Extraction',
        workflowId: 'platform.bulk_historical_extraction_stitch',
        canonicalEventType: 'command.historical_extract_requests',
        mappingSpecId: null,
      });

      const ctx = createMockWorkspaceContext();
      const qc = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 } },
      });

      const html = renderToStaticMarkup(
        <QueryClientProvider client={qc}>
          <IpWorkspaceContext.Provider value={ctx}>
            <StitchDetailDataExplorer
              stitch={streamingStitch}
              activeTab="inbound"
              onTabChange={() => {}}
            />
          </IpWorkspaceContext.Provider>
        </QueryClientProvider>,
      );

      // Verify all 4 primary tabs rendered
      expect(html).toContain('Inbound');
      expect(html).toContain('Replica');
      expect(html).toContain('Records');
      expect(html).toContain('Outbound');

      // Verify GEM is OMITTED
      expect(html).not.toContain('Mappings');
      expect(html).not.toContain('Transactional GEM Enabled');

      // Verify relative order in rendered HTML: Inbound < Replica < Records < Outbound
      const wireIndex = html.indexOf('>Inbound<');
      const docsIndex = html.indexOf('>Replica<');
      const recordsIndex = html.indexOf('>Records<');
      const deliveryIndex = html.indexOf('>Outbound<');

      expect(wireIndex).toBeGreaterThan(-1);
      expect(docsIndex).toBeGreaterThan(wireIndex);
      expect(recordsIndex).toBeGreaterThan(docsIndex);
      expect(deliveryIndex).toBeGreaterThan(recordsIndex);
    });

    it('renders GEM in 5th position for transactional stitches to show source-to-destination mapping', () => {
      const transactionalStitch = createMockStitch({
        id: 'stch_invoice_erp_sync',
        name: 'Invoice Ledger ERP Sync',
        workflowId: 'finance.ledger_erp_sync_stitch',
        canonicalEventType: 'finance.invoice.erp.sync',
        mappingSpecId: 'spec_sap_billing',
      });

      const ctx = createMockWorkspaceContext();
      const qc = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 } },
      });

      const html = renderToStaticMarkup(
        <QueryClientProvider client={qc}>
          <IpWorkspaceContext.Provider value={ctx}>
            <StitchDetailDataExplorer
              stitch={transactionalStitch}
              activeTab="gem"
              onTabChange={() => {}}
            />
          </IpWorkspaceContext.Provider>
        </QueryClientProvider>,
      );

      // Verify Mappings tab rendered
      expect(html).toContain('Mappings');
      expect(html).toContain('Transactional GEM Enabled');

      // Verify source to destination crosswalk headers
      expect(html).toContain('Source Record (App &amp; ID)');
      expect(html).toContain('Destination Record (App &amp; ID)');

      // Verify GEM is 5th (after Outbound)
      const deliveryIndex = html.indexOf('>Outbound<');
      const gemIndex = html.indexOf('>Mappings<');
      expect(gemIndex).toBeGreaterThan(deliveryIndex);
    });

    it('renders scoped DAG node lens banner when selectedNodeKey is provided', () => {
      const stitch = createMockStitch({
        id: 'stch_erp',
        name: 'ERP Stitch',
        workflowId: 'erp_workflow',
        canonicalEventType: 'erp.event',
      });

      const ctx = createMockWorkspaceContext();
      const qc = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 } },
      });

      const html = renderToStaticMarkup(
        <QueryClientProvider client={qc}>
          <IpWorkspaceContext.Provider value={ctx}>
            <StitchDetailDataExplorer
              stitch={stitch}
              activeTab="outbound"
              selectedNodeKey="dispatch_sap_erp"
              onClearNodeFilter={() => {}}
              onTabChange={() => {}}
            />
          </IpWorkspaceContext.Provider>
        </QueryClientProvider>,
      );

      expect(html).toContain('Scoped to DAG Node:');
      expect(html).toContain('dispatch_sap_erp');
      expect(html).toContain('Clear Scoped Lens');
    });

    it('renders outbound delivery records table headers with destination app, status, request, response, sent at', () => {
      const stitch = createMockStitch({
        id: 'stch_erp',
        name: 'ERP Stitch',
        workflowId: 'erp_workflow',
        canonicalEventType: 'erp.event',
      });

      const ctx = createMockWorkspaceContext();
      const qc = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 } },
      });

      const html = renderToStaticMarkup(
        <QueryClientProvider client={qc}>
          <IpWorkspaceContext.Provider value={ctx}>
            <StitchDetailDataExplorer stitch={stitch} activeTab="outbound" onTabChange={() => {}} />
          </IpWorkspaceContext.Provider>
        </QueryClientProvider>,
      );

      expect(html).toContain('Destination App');
      expect(html).toContain('Status');
      expect(html).toContain('Request');
      expect(html).toContain('Response');
      expect(html).toContain('Sent At');
    });

    it('renders inbound delivery records table headers with stream app, request, response, ingested at', () => {
      const stitch = createMockStitch({
        id: 'stch_erp',
        name: 'ERP Stitch',
        workflowId: 'erp_workflow',
        canonicalEventType: 'erp.event',
      });

      const ctx = createMockWorkspaceContext();
      const qc = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 } },
      });

      const html = renderToStaticMarkup(
        <QueryClientProvider client={qc}>
          <IpWorkspaceContext.Provider value={ctx}>
            <StitchDetailDataExplorer stitch={stitch} activeTab="inbound" onTabChange={() => {}} />
          </IpWorkspaceContext.Provider>
        </QueryClientProvider>,
      );

      expect(html).toContain('Wire Record ID');
      expect(html).toContain('Stream / App');
      expect(html).toContain('Request');
      expect(html).toContain('Response');
      expect(html).toContain('Ingested At');
    });

    it('renders executions list when activeTab is executions', () => {
      const stitch = createMockStitch({
        id: 'stch_erp',
        name: 'ERP Stitch',
        workflowId: 'erp_workflow',
        canonicalEventType: 'erp.event',
      });

      const mockRuns = [
        {
          runId: 'run_alpha_01',
          tenantId: 'ten_01',
          workflowId: 'erp_workflow',
          workflowVersion: 1,
          status: 'COMPLETED' as const,
          priority: 'NORMAL',
          concurrencyKey: null,
          idempotencyKey: 'idem_01',
          traceId: 'trc_inv_99881_ok',
          correlationId: null,
          failureCode: null,
          failureDetail: null,
          createdAt: '2026-11-23T10:00:00Z',
          startedAt: '2026-11-23T10:00:01Z',
          finishedAt: '2026-11-23T10:00:02Z',
          steps: [
            {
              stepRunId: 'step_01',
              nodeKey: 'intake',
              status: 'COMPLETED',
              retryCount: 0,
              iterationCount: 1,
              appRetryCount: 0,
              internalRetryCount: 0,
              failureCode: null,
              failureDetail: null,
              createdAt: '2026-11-23T10:00:00Z',
              startedAt: '2026-11-23T10:00:00Z',
              finishedAt: '2026-11-23T10:00:01Z',
            },
          ],
        },
      ];

      const ctx = createMockWorkspaceContext();
      const qc = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 } },
      });

      const html = renderToStaticMarkup(
        <QueryClientProvider client={qc}>
          <IpWorkspaceContext.Provider value={ctx}>
            <StitchDetailDataExplorer
              stitch={stitch}
              activeTab="executions"
              onTabChange={() => {}}
              runs={mockRuns}
              activeRunId="run_alpha_01"
              onSelectRunId={() => {}}
            />
          </IpWorkspaceContext.Provider>
        </QueryClientProvider>,
      );

      // Verify Executions tab header trigger
      expect(html).toContain('Executions');

      // Verify Table Columns
      expect(html).toContain('Run ID');
      expect(html).toContain('Trace ID');
      expect(html).toContain('Step Progress');

      // Verify row content and active state
      expect(html).toContain('run_alpha_01');
      expect(html).toContain('trc_inv_99881_ok');
      expect(html).toContain('Active on DAG');
      expect(html).toContain('1 / 1 steps');
    });
  });
});
