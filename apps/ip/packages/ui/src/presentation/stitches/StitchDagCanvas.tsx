import React from 'react';
import type { StitchNode, StitchStepRun } from '../../domain/stitch';
import { VisualStitchPipeline } from './VisualStitchPipeline';

export interface StitchDagCanvasProps {
  readonly nodes: readonly StitchNode[];
  readonly stepRuns?: readonly StitchStepRun[];
  readonly selectedNodeKey?: string | null;
  readonly onSelectNode?: (nodeKey: string) => void;
}

/**
 * @deprecated Use VisualStitchPipeline directly. This facade ensures zero dual-architecture
 * drift by delegating all rendering to the single canonical dynamic Dagster-style DAG canvas.
 */
export function StitchDagCanvas({
  nodes,
  stepRuns,
  selectedNodeKey,
  onSelectNode,
}: StitchDagCanvasProps) {
  return (
    <VisualStitchPipeline
      definition={{
        workflowId: 'stitch_dag',
        version: 1,
        defaultPriority: 'DEFAULT',
        description: '',
        nodes,
      }}
      stepRuns={stepRuns}
      selectedNodeKey={selectedNodeKey}
      onSelectNode={onSelectNode}
    />
  );
}
