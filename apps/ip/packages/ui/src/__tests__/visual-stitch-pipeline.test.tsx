import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { computeDagLayout } from '../domain/dag/compute-dag-layout';
import { StitchNodeKind } from '../domain/enums';
import type { StitchDefinition, StitchNode } from '../domain/stitch';
import { StitchDagCanvas } from '../presentation/stitches/StitchDagCanvas';
import {
  resolveNodeArchetype,
  VisualStitchPipeline,
} from '../presentation/stitches/VisualStitchPipeline';

describe('VisualStitchPipeline Node Archetype Decoupling', () => {
  const sampleNodes: StitchNode[] = [
    {
      nodeKey: 'fetch_partner_records',
      kind: StitchNodeKind.TASK,
      stepType: 'replica.query_records',
      parents: [],
      edgeCondition: 'ON_SUCCESS',
      effectPolicy: 'READ_ONLY',
      waitEventKey: null,
      queueName: 'staging',
      boundary: 'Enterprise Core (Platform)',
      track: 0,
    },
    {
      nodeKey: 'wait_for_hes_push',
      kind: StitchNodeKind.WAIT_FOR_EVENT,
      stepType: 'hes.callback_listener',
      parents: ['fetch_partner_records'],
      edgeCondition: 'ON_SUCCESS',
      effectPolicy: 'READ_ONLY',
      waitEventKey: 'hes.push.completed',
      queueName: 'external_gate',
      boundary: 'Field Network (HES)',
      track: 0,
    },
    {
      nodeKey: 'dispatch_sap_erp',
      kind: StitchNodeKind.TASK,
      stepType: 'http.post_billing',
      parents: ['wait_for_hes_push'],
      edgeCondition: 'ON_SUCCESS',
      effectPolicy: 'TRANSACTIONAL',
      waitEventKey: null,
      queueName: 'dispatch',
      boundary: 'Field Network (HES)',
      track: 0,
    },
    {
      nodeKey: 'calculate_rollups',
      kind: StitchNodeKind.TASK,
      stepType: 'compute.rollups',
      parents: ['wait_for_hes_push'],
      edgeCondition: 'ON_SUCCESS',
      effectPolicy: 'TRIGGER',
      waitEventKey: null,
      queueName: 'compute',
      boundary: 'Enterprise Core (Platform)',
      track: 0,
    },
  ];

  const sampleDefinition: StitchDefinition = {
    workflowId: 'partner_sync_v2',
    version: 2,
    defaultPriority: 'DEFAULT',
    description: 'Partner Integration Workflow',
    nodes: sampleNodes,
  };

  it('resolves node archetypes deterministically without string sniffing', () => {
    expect(resolveNodeArchetype(sampleNodes[1])).toBe('ASYNC_GATE');
    expect(
      resolveNodeArchetype({
        ...sampleNodes[0],
        waitEventKey: 'custom.event',
      }),
    ).toBe('ASYNC_GATE');

    expect(resolveNodeArchetype(sampleNodes[0])).toBe('DATA_QUERY');
    expect(resolveNodeArchetype(sampleNodes[2])).toBe('STATE_MUTATION');
    expect(
      resolveNodeArchetype({
        ...sampleNodes[2],
        effectPolicy: 'IDEMPOTENT',
      }),
    ).toBe('STATE_MUTATION');
    expect(resolveNodeArchetype(sampleNodes[3])).toBe('GENERIC_TASK');
  });

  it('renders dynamic DAG canvas with cubic Bezier paths, boundary lines, zero clutter', () => {
    const html = renderToStaticMarkup(
      <VisualStitchPipeline
        definition={sampleDefinition}
        stitch={{
          id: 'st_123',
          tenantId: 'tenant_main',
          name: 'Partner Integration Pipeline',
          workflowId: 'partner_sync_v2',
          workflowVersion: 2,
          canonicalEventType: 'canonical.event.sample',
          isTrigger: true,
          conditionEventKey: null,
          idempotencyKeyField: 'record_id',
          concurrencyKeyField: null,
          resourceHintField: null,
          isActive: true,
        }}
      />,
    );

    expect(html).toContain('Trigger:');
    expect(html).toContain('canonical.event.sample');
    expect(html).not.toContain('__ingress_trigger__');

    expect(html).toContain('fetch_partner_records');
    expect(html).toContain('wait_for_hes_push');
    expect(html).toContain('dispatch_sap_erp');
    expect(html).toContain('calculate_rollups');

    expect(html).toContain('⚡ ASYNC GATE');
    expect(html).toContain('wait_for: hes.push.completed');

    expect(html).toContain('dagster-arrow');
    expect(html).toContain('<path');

    // Zero internal clutter
    expect(html).not.toContain('Configured');
    expect(html).not.toContain('PURE');
  });

  it('dynamically computes dual-track circuit with fanout boundaries', () => {
    const roundTripNodes: StitchNode[] = [
      // Track 0: Outbound
      {
        nodeKey: 'request_received',
        kind: StitchNodeKind.TASK,
        stepType: 'trigger.ingress',
        parents: [],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'default',
        boundary: 'Enterprise Core (MDM)',
        track: 0,
      },
      {
        nodeKey: 'slice_date_range',
        kind: StitchNodeKind.TASK,
        stepType: 'orchestration.slice_daily_chunks',
        parents: ['request_received'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'default',
        boundary: 'Enterprise Core (MDM)',
        track: 0,
      },
      {
        nodeKey: 'fanout_hes_partitions',
        kind: StitchNodeKind.TASK,
        stepType: 'orchestration.fanout_by_connection',
        parents: ['slice_date_range'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'default',
        boundary: 'Enterprise Core (MDM)',
        track: 0,
      },
      // 3 parallel fanout children
      {
        nodeKey: 'dispatch_itron_hes',
        kind: StitchNodeKind.TASK,
        stepType: 'http.post_extract',
        parents: ['fanout_hes_partitions'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'RECONCILABLE_EFFECT',
        waitEventKey: null,
        queueName: 'default',
        boundary: 'Field Network (HES)',
        track: 0,
      },
      {
        nodeKey: 'dispatch_landis_gyr_hes',
        kind: StitchNodeKind.TASK,
        stepType: 'http.post_extract',
        parents: ['fanout_hes_partitions'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'RECONCILABLE_EFFECT',
        waitEventKey: null,
        queueName: 'default',
        boundary: 'Field Network (HES)',
        track: 0,
      },
      // Track 1: Inbound
      {
        nodeKey: 'batch_push_received',
        kind: StitchNodeKind.TASK,
        stepType: 'trigger.ingress',
        parents: ['dispatch_itron_hes', 'dispatch_landis_gyr_hes'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'default',
        boundary: 'Field Network (HES)',
        track: 1,
      },
      {
        nodeKey: 'publish_to_kafka',
        kind: StitchNodeKind.TASK,
        stepType: 'kafka.publish_intervals',
        parents: ['batch_push_received'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'IDEMPOTENT_EFFECT',
        waitEventKey: null,
        queueName: 'default',
        boundary: 'Enterprise Core (MDM)',
        track: 1,
      },
    ];

    const layout = computeDagLayout(roundTripNodes);

    // Verify all nodes placed
    expect(layout.nodes.length).toBe(7);

    // Verify fanout: dispatch_itron_hes and dispatch_landis_gyr_hes placed in the same column (rank 3)
    const itronNode = layout.nodes.find((n) => n.node.nodeKey === 'dispatch_itron_hes');
    const landisNode = layout.nodes.find((n) => n.node.nodeKey === 'dispatch_landis_gyr_hes');
    expect(itronNode).toBeDefined();
    expect(landisNode).toBeDefined();
    expect(itronNode!.x).toBe(landisNode!.x);
    expect(itronNode!.y).not.toBe(landisNode!.y); // stacked in different rows

    // Verify dual-track positioning: Track 1 node placed below Track 0
    const batchNode = layout.nodes.find((n) => n.node.nodeKey === 'batch_push_received');
    expect(batchNode!.track).toBe(1);
    expect(batchNode!.y).toBeGreaterThan(itronNode!.y);

    // Verify cross-track edge created for returning arc
    const crossTrackEdge = layout.edges.find((e) => e.isCrossTrack);
    expect(crossTrackEdge).toBeDefined();
    expect(crossTrackEdge!.toKey).toBe('batch_push_received');

    // Verify dynamic two-perimeter boundary dividers
    expect(layout.boundaries.length).toBe(2);
    const sourcePerimeter = layout.boundaries.find((b) => b.type === 'source-perimeter');
    const destPerimeter = layout.boundaries.find((b) => b.type === 'destination-perimeter');
    expect(sourcePerimeter).toBeDefined();
    expect(destPerimeter).toBeDefined();
    expect(sourcePerimeter!.label).toBe('Enterprise Core (MDM)');
    expect(destPerimeter!.label).toBe('Field Network (HES)');

    // Invariant: Source line is on extreme left, Destination line is on extreme right
    expect(sourcePerimeter!.x).toBeLessThan(itronNode!.x);
    expect(destPerimeter!.x).toBeGreaterThan(itronNode!.x + itronNode!.width);

    // Invariant: NOTHING extends beyond the vertical lines
    for (const n of layout.nodes) {
      expect(n.x).toBeGreaterThan(sourcePerimeter!.x);
      expect(n.x + n.width).toBeLessThan(destPerimeter!.x);
    }
    for (const e of layout.edges) {
      const edgeReach = e.isCrossTrack ? e.sourceX + (e.curveOffset ?? 0) : e.targetX;
      expect(edgeReach).toBeLessThan(destPerimeter!.x);
    }

    // Render HTML and verify visual markers
    const html = renderToStaticMarkup(
      <VisualStitchPipeline
        definition={{
          workflowId: 'platform.hes_historical_extraction_stitch',
          version: 1,
          defaultPriority: 'BULK',
          description: 'Round-trip journey',
          nodes: roundTripNodes,
        }}
      />,
    );

    expect(html).toContain('Enterprise Core (MDM)');
    expect(html).toContain('Field Network (HES)');
    expect(html).toContain('dagster-arrow-return');
    expect(html).toContain('dispatch_itron_hes');
    expect(html).toContain('dispatch_landis_gyr_hes');
    expect(html).toContain('batch_push_received');
    expect(html).toContain('publish_to_kafka');
  });

  it('lays out full 18-node multi-vendor pipeline with 3 independent streaming lanes, zero consolidation', () => {
    const enterpriseBoundary = 'Enterprise Core (MDM / Kafka)';
    const fieldBoundary = 'Field Infrastructure (HES)';

    const full18Nodes: StitchNode[] = [
      // Track 0: Outbound Slicing & Multi-HES Fanout
      {
        nodeKey: 'request_received',
        kind: StitchNodeKind.TASK,
        stepType: 'trigger.ingress',
        parents: [],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'default',
        boundary: enterpriseBoundary,
        track: 0,
      },
      {
        nodeKey: 'slice_date_range',
        kind: StitchNodeKind.TASK,
        stepType: 'orchestration.slice_daily_chunks',
        parents: ['request_received'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'default',
        boundary: enterpriseBoundary,
        track: 0,
      },
      {
        nodeKey: 'fanout_hes_partitions',
        kind: StitchNodeKind.TASK,
        stepType: 'orchestration.fanout_by_connection',
        parents: ['slice_date_range'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'default',
        boundary: enterpriseBoundary,
        track: 0,
      },
      {
        nodeKey: 'dispatch_itron_hes',
        kind: StitchNodeKind.TASK,
        stepType: 'http.post_extract',
        parents: ['fanout_hes_partitions'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'RECONCILABLE_EFFECT',
        waitEventKey: null,
        queueName: 'default',
        boundary: fieldBoundary,
        track: 0,
      },
      {
        nodeKey: 'dispatch_landis_gyr_hes',
        kind: StitchNodeKind.TASK,
        stepType: 'http.post_extract',
        parents: ['fanout_hes_partitions'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'RECONCILABLE_EFFECT',
        waitEventKey: null,
        queueName: 'default',
        boundary: fieldBoundary,
        track: 0,
      },
      {
        nodeKey: 'dispatch_siemens_hes',
        kind: StitchNodeKind.TASK,
        stepType: 'http.post_extract',
        parents: ['fanout_hes_partitions'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'RECONCILABLE_EFFECT',
        waitEventKey: null,
        queueName: 'default',
        boundary: fieldBoundary,
        track: 0,
      },

      // Track 1: Inbound Stream 1 (Send as it arrives)
      {
        nodeKey: 'partner_batch_received',
        kind: StitchNodeKind.TASK,
        stepType: 'trigger.ingress',
        parents: ['dispatch_itron_hes'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'default',
        boundary: fieldBoundary,
        track: 1,
      },
      {
        nodeKey: 'decompress_and_parse_itron',
        kind: StitchNodeKind.TASK,
        stepType: 'batch.parse_openway_batch',
        parents: ['partner_batch_received'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'default',
        boundary: enterpriseBoundary,
        track: 1,
      },
      {
        nodeKey: 'normalize_itron_intervals',
        kind: StitchNodeKind.TASK,
        stepType: 'batch.normalize_intervals',
        parents: ['decompress_and_parse_itron'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'default',
        boundary: enterpriseBoundary,
        track: 1,
      },
      {
        nodeKey: 'publish_itron_to_kafka',
        kind: StitchNodeKind.TASK,
        stepType: 'kafka.publish_intervals',
        parents: ['normalize_itron_intervals'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'IDEMPOTENT_EFFECT',
        waitEventKey: null,
        queueName: 'default',
        boundary: enterpriseBoundary,
        track: 1,
      },

      // Track 1: Inbound Stream 2 (Landis+Gyr - Send as it arrives)
      {
        nodeKey: 'landis_batch_received',
        kind: StitchNodeKind.TASK,
        stepType: 'trigger.ingress',
        parents: ['dispatch_landis_gyr_hes'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'default',
        boundary: fieldBoundary,
        track: 1,
      },
      {
        nodeKey: 'decompress_and_parse_landis',
        kind: StitchNodeKind.TASK,
        stepType: 'landis.parse_cim_batch',
        parents: ['landis_batch_received'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'default',
        boundary: enterpriseBoundary,
        track: 1,
      },
      {
        nodeKey: 'normalize_landis_intervals',
        kind: StitchNodeKind.TASK,
        stepType: 'landis.normalize_intervals',
        parents: ['decompress_and_parse_landis'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'default',
        boundary: enterpriseBoundary,
        track: 1,
      },
      {
        nodeKey: 'publish_landis_to_kafka',
        kind: StitchNodeKind.TASK,
        stepType: 'kafka.publish_intervals',
        parents: ['normalize_landis_intervals'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'IDEMPOTENT_EFFECT',
        waitEventKey: null,
        queueName: 'default',
        boundary: enterpriseBoundary,
        track: 1,
      },

      // Track 1: Inbound Stream 3 (Siemens - Send as it arrives)
      {
        nodeKey: 'siemens_batch_received',
        kind: StitchNodeKind.TASK,
        stepType: 'trigger.ingress',
        parents: ['dispatch_siemens_hes'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'default',
        boundary: fieldBoundary,
        track: 1,
      },
      {
        nodeKey: 'decompress_and_parse_siemens',
        kind: StitchNodeKind.TASK,
        stepType: 'siemens.parse_energyip_batch',
        parents: ['siemens_batch_received'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'default',
        boundary: enterpriseBoundary,
        track: 1,
      },
      {
        nodeKey: 'normalize_siemens_intervals',
        kind: StitchNodeKind.TASK,
        stepType: 'siemens.normalize_intervals',
        parents: ['decompress_and_parse_siemens'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'PURE',
        waitEventKey: null,
        queueName: 'default',
        boundary: enterpriseBoundary,
        track: 1,
      },
      {
        nodeKey: 'publish_siemens_to_kafka',
        kind: StitchNodeKind.TASK,
        stepType: 'kafka.publish_intervals',
        parents: ['normalize_siemens_intervals'],
        edgeCondition: 'ON_SUCCESS',
        effectPolicy: 'IDEMPOTENT_EFFECT',
        waitEventKey: null,
        queueName: 'default',
        boundary: enterpriseBoundary,
        track: 1,
      },
    ];

    const layout = computeDagLayout(full18Nodes);

    // Verify exactly 18 nodes placed
    expect(layout.nodes).toHaveLength(18);

    // Verify 3 distinct parallel Kafka publishers on Track 1 (zero consolidation)
    const kafkaNodes = layout.nodes.filter((n) =>
      ['publish_itron_to_kafka', 'publish_landis_to_kafka', 'publish_siemens_to_kafka'].includes(
        n.node.nodeKey,
      ),
    );
    expect(kafkaNodes).toHaveLength(3);
    // All 3 Kafka nodes reside in the leftmost column of Track 1 (rank 3 -> colIndex 0)
    expect(kafkaNodes[0].x).toBe(kafkaNodes[1].x);
    expect(kafkaNodes[1].x).toBe(kafkaNodes[2].x);
    // Each stacked in separate autonomous rows
    expect(kafkaNodes[0].y).not.toBe(kafkaNodes[1].y);
    expect(kafkaNodes[1].y).not.toBe(kafkaNodes[2].y);

    // Verify 3 concentric cross-track returning arcs
    const crossEdges = layout.edges.filter((e) => e.isCrossTrack);
    expect(crossEdges).toHaveLength(3);
    const curveOffsets = crossEdges.map((e) => e.curveOffset ?? 0);
    // Concentric nesting: offsets must be strictly descending or strictly distinct
    expect(new Set(curveOffsets).size).toBe(3);

    // Verify Two-Perimeter Bounded Corridor invariants
    const sourcePerimeter = layout.boundaries.find((b) => b.type === 'source-perimeter');
    const destPerimeter = layout.boundaries.find((b) => b.type === 'destination-perimeter');
    expect(sourcePerimeter).toBeDefined();
    expect(destPerimeter).toBeDefined();
    expect(sourcePerimeter!.label).toBe(enterpriseBoundary);
    expect(destPerimeter!.label).toBe(fieldBoundary);

    // Invariant: NOTHING extends beyond the vertical lines
    for (const n of layout.nodes) {
      expect(n.x).toBeGreaterThan(sourcePerimeter!.x);
      expect(n.x + n.width).toBeLessThan(destPerimeter!.x);
    }
    for (const e of layout.edges) {
      const reach = e.isCrossTrack ? e.sourceX + (e.curveOffset ?? 0) : e.targetX;
      expect(reach).toBeLessThan(destPerimeter!.x);
    }

    // Render HTML and verify all 18 nodes and badges render
    const html = renderToStaticMarkup(
      <VisualStitchPipeline
        definition={{
          workflowId: 'platform.hes_historical_extraction_stitch',
          version: 1,
          defaultPriority: 'BULK',
          description: 'Full 18-node multi-vendor pipeline',
          nodes: full18Nodes,
        }}
      />,
    );

    expect(html).toContain('18 DAG Nodes');
    expect(html).toContain('publish_itron_to_kafka');
    expect(html).toContain('publish_landis_to_kafka');
    expect(html).toContain('publish_siemens_to_kafka');
    expect(html).toContain('Enterprise Core (MDM / Kafka)');
    expect(html).toContain('Field Infrastructure (HES)');
    expect(html).toContain('dagster-arrow-return');
  });

  it('preserves backwards-compatibility via StitchDagCanvas facade', () => {
    const html = renderToStaticMarkup(
      <StitchDagCanvas nodes={sampleNodes} selectedNodeKey="fetch_partner_records" />,
    );

    expect(html).toContain('fetch_partner_records');
    expect(html).toContain('wait_for_hes_push');
    expect(html).toContain('dispatch_sap_erp');
    expect(html).toContain('⚡ ASYNC GATE');
  });
});
