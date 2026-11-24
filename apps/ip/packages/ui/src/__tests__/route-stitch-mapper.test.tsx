import { ok } from '@soopa/ui';
import { RecordingLoggerFake } from '@soopa/ui/testing';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ipQueryKeys } from '../application/query-keys';
import { ConnectionEntitiesSyncTab } from '../presentation/connections/ConnectionEntitiesSyncTab';
import { DestinationSchemaMonacoEditor } from '../presentation/stitch-mapper/DestinationSchemaMonacoEditor';
import { IpStitchFieldMapperPage } from '../presentation/stitch-mapper/IpStitchFieldMapperPage';
import { IpUIProvider } from '../provider/IpUIProvider';
import {
  createInMemoryIpWorkspaceSeed,
  SEED_CATALOG_APPS,
  SEED_CONNECTION,
  SEED_CONNECTION_ENTITY,
  SEED_CONNECTION_ID,
  SEED_DISCOVERED_CATALOG,
  SEED_STITCH_DEFINITION,
  SEED_TENANT_ID,
  SEED_TRANSFORMATION,
  SEED_TRANSFORMERS,
} from '../testing';

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
    ipQueryKeys.transformations.byConnection(SEED_TENANT_ID, SEED_CONNECTION_ID),
    ok([SEED_TRANSFORMATION]),
  );
  qc.setQueryData(ipQueryKeys.transformations.transformers(SEED_TENANT_ID), ok(SEED_TRANSFORMERS));
  qc.setQueryData(ipQueryKeys.stitches.definitions(SEED_TENANT_ID), ok([SEED_STITCH_DEFINITION]));

  return qc;
}

describe('Stitch Field Mapper Page', () => {
  it('renders IpStitchFieldMapperPage as a single cohesive workspace when source plus destination are fully selected', () => {
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
          <IpStitchFieldMapperPage
            initialSourceConnectionId={SEED_CONNECTION_ID}
            initialStreamName="records_alpha"
            initialTargetConnectionId={SEED_CONNECTION_ID}
            initialTargetTopic="records_alpha"
          />
        </IpUIProvider>
      </QueryClientProvider>,
    );

    expect(html).toContain('Stitch &amp; Field Mapper');
    expect(html).not.toContain('workbench');
    expect(html).toContain('Source Connection');
    expect(html).toContain('Entity');
    expect(html).toContain('Destination Connection');
    expect(html).toContain('Destination Entity / Topic / Directory');
    expect(html).toContain('Source');
    expect(html).toContain('Mapping');
    expect(html).toContain('Destination');
    expect(html).toContain('Deploy &amp; Activate Stitch');
    expect(html).toContain('Live Preview');
    expect(html).not.toContain('Oracle MDM Wire Format');
    expect(html).not.toContain('C2M Service Events');
    expect(html).not.toContain('Schema Editor (Upload/Drag &amp; Drop/Paste)');
    expect(html).not.toContain('>Excluded<');
    expect(html).toContain('-- Unmapped --');
  });

  it('renders clean unselected state with empty placeholder when pipeline is not configured', () => {
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
          <IpStitchFieldMapperPage />
        </IpUIProvider>
      </QueryClientProvider>,
    );

    expect(html).toContain('Stitch &amp; Field Mapper');
    expect(html).toContain('Configure Source and Destination');
    expect(html).toContain(
      'Select a Source Connection &amp; Entity on the left, and a Destination Connection &amp; Topic/Entity on the right',
    );
    expect(html).not.toContain('Live Preview');
  });

  it('renders destination incomplete state when only source connection plus entity are provided', () => {
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
          <IpStitchFieldMapperPage
            initialSourceConnectionId={SEED_CONNECTION_ID}
            initialStreamName="records_alpha"
          />
        </IpUIProvider>
      </QueryClientProvider>,
    );

    expect(html).toContain('Stitch &amp; Field Mapper');
    expect(html).toContain('Destination Configuration Incomplete');
    expect(html).toContain(
      'Select a Destination Connection and enter the Destination Topic, Entity, or Directory',
    );
    expect(html).not.toContain('Live Preview');
  });

  it('renders Normalization column with Stitch button in ConnectionEntitiesSyncTab', () => {
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
          <ConnectionEntitiesSyncTab
            connectionId={SEED_CONNECTION_ID}
            connection={SEED_CONNECTION}
            onOpenTrace={() => {}}
            onProblem={() => {}}
          />
        </IpUIProvider>
      </QueryClientProvider>,
    );

    expect(html).toContain('Normalization');
    expect(html).toContain('Stitch');
  });

  it('navigates to the stitch mapper when toStitchMapper is called on navigation', () => {
    const harness = createInMemoryIpWorkspaceSeed();
    harness.navigation.toStitchMapper?.({
      sourceConnectionId: 'conn_source_01',
      streamName: 'records_alpha',
      targetConnectionId: 'conn_dest_01',
      targetTopic: 'records_alpha_sink',
    });

    expect(harness.navigation.visited).toContain(
      '/tenant/ip/stitches/mapper?sourceConnectionId=conn_source_01&stream=records_alpha&targetConnectionId=conn_dest_01&targetTopic=records_alpha_sink',
    );
  });

  it('renders DestinationSchemaMonacoEditor with on-editor upload action plus footer clear format', () => {
    const htmlEmpty = renderToStaticMarkup(
      <DestinationSchemaMonacoEditor
        value=""
        onChange={() => {}}
        onClear={() => {}}
        onApply={() => {}}
      />,
    );

    expect(htmlEmpty).toContain('Paste');
    expect(htmlEmpty).toContain('Drag &amp; Drop');
    expect(htmlEmpty).toContain('Upload');
    expect(htmlEmpty).toContain('Clear');
    expect(htmlEmpty).toContain('Format');
    expect(htmlEmpty).not.toContain('Drag & drop file or upload');

    const htmlFilled = renderToStaticMarkup(
      <DestinationSchemaMonacoEditor
        value={JSON.stringify({ recordId: 'REC-1', metricVal: 100 }, null, 2)}
        onChange={() => {}}
        onClear={() => {}}
        onApply={() => {}}
      />,
    );

    expect(htmlFilled).toContain('Clear');
    expect(htmlFilled).toContain('Format');
    expect(htmlFilled).not.toContain('Drag & drop file or upload');
  });

  it('persists declarative mapping spec with linked stitch definition in trinity workflow', async () => {
    const harness = createInMemoryIpWorkspaceSeed();

    const saveSpecRes = await harness.repositories.mappingSpecs.saveMappingSpec(SEED_TENANT_ID, {
      name: 'Alpha to Target Wire Translation',
      description: 'Projects alpha canonical to wire format',
      sourceType: 'canonical.records_alpha',
      targetConnectionId: SEED_CONNECTION_ID,
      targetEntityName: 'records_alpha',
      rules: [
        {
          targetField: 'external_id',
          ruleType: 'DIRECT',
          sourceField: 'record_id',
        },
        {
          targetField: 'wire_ver',
          ruleType: 'CONSTANT',
          constantValue: '2.0',
        },
      ],
      isActive: true,
    });

    expect(saveSpecRes.ok).toBe(true);
    if (!saveSpecRes.ok) return;
    const spec = saveSpecRes.value;
    expect(spec.id).toContain('ip_fmap_');

    const stitchRes = await harness.repositories.stitches.registerStitch(SEED_TENANT_ID, {
      name: 'Alpha Wire Stitch',
      mappingSpecId: spec.id,
      workflowId: 'stitch.records_alpha',
      workflowVersion: 1,
      canonicalEventType: 'canonical.records_alpha',
      isTrigger: true,
      idempotencyKeyField: 'record_id',
      isActive: true,
    });

    expect(stitchRes.ok).toBe(true);
    if (!stitchRes.ok) return;
    const stitch = stitchRes.value;
    expect(stitch.mappingSpecId).toBe(spec.id);

    const fetchedSpec = await harness.repositories.mappingSpecs.getMappingSpec(
      SEED_TENANT_ID,
      spec.id,
    );
    expect(fetchedSpec.ok).toBe(true);
    if (fetchedSpec.ok) {
      expect(fetchedSpec.value.name).toBe('Alpha to Target Wire Translation');
      expect(fetchedSpec.value.rules.length).toBe(2);
    }
  });
});
