import { Button, cn, StatusBadge, StatusTone } from '@soopa/ui';
import { Clock, Cpu, Hourglass } from 'lucide-react';
import React, { useMemo } from 'react';
import {
  computeDagLayout,
  type DagLayoutEdge,
  type DagLayoutNode,
} from '../../domain/dag/compute-dag-layout';
import { StitchNodeKind } from '../../domain/enums';
import type { StitchNode, StitchStepRun } from '../../domain/stitch';
import { mapStitchRunStatusTone } from '../shared/status-mapping';

export interface StitchDagCanvasProps {
  readonly nodes: readonly StitchNode[];
  readonly stepRuns?: readonly StitchStepRun[];
  readonly selectedNodeKey?: string | null;
  readonly onSelectNode?: (nodeKey: string) => void;
}

function buildCubicBezierPath(edge: DagLayoutEdge): string {
  const deltaX = Math.max(40, (edge.targetX - edge.sourceX) * 0.5);
  const c1X = edge.sourceX + deltaX;
  const c2X = edge.targetX - deltaX;
  return `M ${edge.sourceX} ${edge.sourceY} C ${c1X} ${edge.sourceY}, ${c2X} ${edge.targetY}, ${edge.targetX} ${edge.targetY}`;
}

function resolveEdgeStrokeClass(condition: string): string {
  if (condition === 'ON_FAILURE') {
    return 'stroke-status-warning-fg';
  }
  if (condition === 'ON_SUCCESS') {
    return 'stroke-status-healthy-fg';
  }
  return 'stroke-muted-foreground';
}

function resolveKindHeaderClass(kind: string): string {
  if (kind === StitchNodeKind.WAIT_FOR_EVENT) {
    return 'bg-status-warning-bg text-status-warning-fg border-status-warning-border';
  }
  if (kind === StitchNodeKind.SLEEP) {
    return 'bg-muted text-muted-foreground border-border';
  }
  return 'bg-primary text-primary-foreground border-primary';
}

function KindIcon({ kind }: { readonly kind: string }) {
  if (kind === StitchNodeKind.WAIT_FOR_EVENT) {
    return <Hourglass className="h-3.5 w-3.5" />;
  }
  if (kind === StitchNodeKind.SLEEP) {
    return <Clock className="h-3.5 w-3.5" />;
  }
  return <Cpu className="h-3.5 w-3.5" />;
}

function DagNodeCard({
  item,
  stepRun,
  isSelected,
  onSelect,
}: {
  readonly item: DagLayoutNode;
  readonly stepRun: StitchStepRun | undefined;
  readonly isSelected: boolean;
  readonly onSelect?: (nodeKey: string) => void;
}) {
  const { node } = item;

  return (
    <div
      style={{
        left: item.x,
        top: item.y,
        width: item.width,
        height: item.height,
      }}
      className="absolute"
    >
      <Button
        type="button"
        variant="outline"
        onClick={() => onSelect?.(node.nodeKey)}
        className={cn(
          'h-full w-full flex-col items-stretch justify-between overflow-hidden rounded-xl bg-card p-0 text-left shadow-xs transition-all hover:border-primary',
          isSelected && 'border-primary ring-2 ring-primary/50',
        )}
      >
        <div
          className={cn(
            'flex items-center justify-between border-b px-3 py-1.5 text-xs font-bold',
            resolveKindHeaderClass(node.kind),
          )}
        >
          <span className="inline-flex items-center gap-1.5">
            <KindIcon kind={node.kind} />
            <span>{node.kind}</span>
          </span>
          <span className="font-mono font-normal opacity-90">{node.queueName}</span>
        </div>

        <div className="flex flex-1 flex-col justify-between px-3 py-2">
          <div className="truncate font-mono text-xs font-semibold text-foreground">
            {node.nodeKey}
          </div>
          <div className="flex items-center justify-between gap-1">
            <span className="truncate font-mono text-xs text-muted-foreground">
              {node.waitEventKey ?? node.stepType}
            </span>
            {stepRun ? (
              <StatusBadge label={stepRun.status} tone={mapStitchRunStatusTone(stepRun.status)} />
            ) : (
              <StatusBadge label={node.effectPolicy} tone={StatusTone.NEUTRAL} />
            )}
          </div>
        </div>
      </Button>
    </div>
  );
}

export function StitchDagCanvas({
  nodes,
  stepRuns = [],
  selectedNodeKey,
  onSelectNode,
}: StitchDagCanvasProps) {
  const layout = useMemo(() => computeDagLayout(nodes), [nodes]);
  const stepByNodeKey = useMemo(() => new Map(stepRuns.map((sr) => [sr.nodeKey, sr])), [stepRuns]);

  if (nodes.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        This Stitch workflow definition has no DAG nodes.
      </div>
    );
  }

  return (
    <div
      tabIndex={0}
      role="region"
      aria-label="Interactive Stitch Topological DAG Canvas"
      className="overflow-x-auto rounded-2xl border border-border bg-accent/25 p-2 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      <div style={{ width: layout.width, height: layout.height }} className="relative mx-auto">
        <svg
          width={layout.width}
          height={layout.height}
          className="pointer-events-none absolute inset-0"
          aria-hidden="true"
        >
          {layout.edges.map((edge) => (
            <path
              key={edge.id}
              d={buildCubicBezierPath(edge)}
              fill="none"
              strokeWidth={2.25}
              strokeDasharray={edge.condition === 'ON_FAILURE' ? '6 4' : undefined}
              className={resolveEdgeStrokeClass(edge.condition)}
            />
          ))}
        </svg>

        {layout.nodes.map((item) => (
          <DagNodeCard
            key={item.node.nodeKey}
            item={item}
            stepRun={stepByNodeKey.get(item.node.nodeKey)}
            isSelected={selectedNodeKey === item.node.nodeKey}
            onSelect={onSelectNode}
          />
        ))}
      </div>
    </div>
  );
}
