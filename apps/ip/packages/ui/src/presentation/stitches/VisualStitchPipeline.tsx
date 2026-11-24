import { Button, cn, StatusBadge, StatusTone } from '@soopa/ui';
import { Cpu, Database, Hourglass, RotateCcw, Send, Workflow } from 'lucide-react';
import React, { useMemo, useState } from 'react';
import { computeDagLayout, type DagLayoutEdge } from '../../domain/dag/compute-dag-layout';
import { StitchNodeKind } from '../../domain/enums';
import type { Stitch, StitchDefinition, StitchNode, StitchStepRun } from '../../domain/stitch';
import { mapStitchRunStatusTone } from '../shared/status-mapping';

export type NodeArchetype = 'ASYNC_GATE' | 'STATE_MUTATION' | 'DATA_QUERY' | 'GENERIC_TASK';

/**
 * Deterministically resolves a node's visual and semantic archetype
 * from strongly-typed domain properties without substring heuristics.
 */
export function resolveNodeArchetype(node: StitchNode): NodeArchetype {
  if (node.kind === StitchNodeKind.WAIT_FOR_EVENT || Boolean(node.waitEventKey)) {
    return 'ASYNC_GATE';
  }
  if (
    node.effectPolicy === 'TRANSACTIONAL' ||
    node.effectPolicy === 'IDEMPOTENT' ||
    node.effectPolicy === 'IDEMPOTENT_EFFECT' ||
    node.effectPolicy === 'RECONCILABLE_EFFECT'
  ) {
    return 'STATE_MUTATION';
  }
  if (node.effectPolicy === 'READ_ONLY') {
    return 'DATA_QUERY';
  }
  return 'GENERIC_TASK';
}

function buildSvgPath(edge: DagLayoutEdge): string {
  if (edge.isCrossTrack) {
    // Cross-track concentric U-turn returning arc
    const curveOffset = edge.curveOffset ?? 90;
    return `M ${edge.sourceX} ${edge.sourceY} C ${edge.sourceX + curveOffset} ${edge.sourceY}, ${edge.targetX + curveOffset} ${edge.targetY}, ${edge.targetX} ${edge.targetY}`;
  }
  if (edge.direction === 'rtl') {
    // Inbound track: flows Right -> Left
    const deltaX = Math.max(48, (edge.sourceX - edge.targetX) * 0.5);
    return `M ${edge.sourceX} ${edge.sourceY} C ${edge.sourceX - deltaX} ${edge.sourceY}, ${edge.targetX + deltaX} ${edge.targetY}, ${edge.targetX} ${edge.targetY}`;
  }
  // Outbound track: flows Left -> Right
  const deltaX = Math.max(48, (edge.targetX - edge.sourceX) * 0.5);
  return `M ${edge.sourceX} ${edge.sourceY} C ${edge.sourceX + deltaX} ${edge.sourceY}, ${edge.targetX - deltaX} ${edge.targetY}, ${edge.targetX} ${edge.targetY}`;
}

export interface VisualStitchPipelineProps {
  readonly stitch?: Stitch | null;
  readonly definition?: StitchDefinition | null;
  readonly stepRuns?: readonly StitchStepRun[];
  readonly selectedNodeKey?: string | null;
  readonly onSelectNode?: (nodeKey: string) => void;
  readonly onResetSelection?: () => void;
  // Optional backward-compatibility props for external callers
  readonly activeTab?: string;
  readonly onSelectStage?: (stageKey: string) => void;
  readonly showDagCanvas?: boolean;
  readonly onToggleDagCanvas?: () => void;
}

export function VisualStitchPipeline({
  stitch,
  definition,
  stepRuns = [],
  selectedNodeKey,
  onSelectNode,
  onResetSelection,
  onSelectStage,
}: VisualStitchPipelineProps) {
  const [internalSelectedKey, setInternalSelectedKey] = useState<string | null>(null);
  const activeSelectedKey = selectedNodeKey ?? internalSelectedKey;

  // Pure mathematical graph without synthetic node mutation
  const rawNodes = useMemo(() => definition?.nodes ?? [], [definition]);
  const layout = useMemo(() => computeDagLayout(rawNodes), [rawNodes]);
  const stepByNodeKey = useMemo(() => new Map(stepRuns.map((sr) => [sr.nodeKey, sr])), [stepRuns]);

  const workflowId = definition?.workflowId ?? stitch?.workflowId ?? 'stitch_workflow';
  const canonicalType = stitch?.canonicalEventType;

  const handleCardClick = (node: StitchNode) => {
    setInternalSelectedKey(node.nodeKey);
    onSelectNode?.(node.nodeKey);

    // Contextual lens: Trigger appropriate Data Plane stage
    if (onSelectStage) {
      const k = node.nodeKey.toLowerCase();
      if (node.boundary === 'source' || k.startsWith('source:') || k.includes('inbound')) {
        onSelectStage('inbound');
      } else if (
        node.boundary === 'destination' ||
        k.includes('dispatch') ||
        k.includes('outbound')
      ) {
        onSelectStage('outbound');
      } else if (k.includes('replica') || k.includes('stage')) {
        onSelectStage('replica');
      } else if (k.includes('normalize') || k.includes('cim') || k.includes('transform')) {
        onSelectStage('normalized');
      } else {
        const archetype = resolveNodeArchetype(node);
        if (archetype === 'DATA_QUERY') {
          onSelectStage('replica');
        } else if (archetype === 'STATE_MUTATION') {
          onSelectStage('outbound');
        } else {
          onSelectStage('normalized');
        }
      }
    }
  };

  const handleResetSelection = () => {
    setInternalSelectedKey(null);
    onResetSelection?.();
  };

  return (
    <div className="rounded-xl border border-border bg-card/60 shadow-sm overflow-hidden">
      {/* Dagster-Style Canvas Top Header Toolbar */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 px-4 py-3 border-b border-border/70 bg-card">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-lg flex items-center justify-center border bg-primary/10 text-primary border-primary/20">
            <Workflow className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono font-semibold text-xs text-foreground">{workflowId}</span>
              <span className="font-mono text-[10px] px-1.5 py-0.2 bg-muted text-muted-foreground rounded border border-border/60">
                v{definition?.version ?? stitch?.workflowVersion ?? 1}
              </span>
              {stitch?.isActive !== undefined && (
                <StatusBadge
                  label={stitch.isActive ? 'ACTIVE' : 'PAUSED'}
                  tone={stitch.isActive ? StatusTone.HEALTHY : StatusTone.WARNING}
                />
              )}
            </div>
            {canonicalType && (
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground mt-0.5">
                <span>Trigger:</span>
                <span className="font-mono font-medium text-foreground">{canonicalType}</span>
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] text-muted-foreground px-2 py-1 rounded bg-muted/50 border border-border/50">
            {rawNodes.length} {rawNodes.length === 1 ? 'DAG Node' : 'DAG Nodes'} ·{' '}
            {layout.edges.length} {layout.edges.length === 1 ? 'Edge' : 'Edges'}
          </span>
          {activeSelectedKey && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={handleResetSelection}
              className="h-7 text-xs gap-1 text-muted-foreground hover:text-foreground"
            >
              <RotateCcw className="h-3 w-3" />
              <span>Reset Selection</span>
            </Button>
          )}
        </div>
      </div>

      {/* Dagster-Style Interactive Canvas Area */}
      <div
        tabIndex={0}
        role="region"
        aria-label="Interactive Stitch Topological DAG Canvas"
        className="relative overflow-x-auto overflow-y-auto p-6 min-h-[260px] max-h-[720px] bg-muted/20 [background-image:radial-gradient(rgba(120,120,120,0.22)_1px,transparent_1px)] [background-size:16px_16px] focus-visible:outline-none"
      >
        {rawNodes.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border p-10 text-center text-xs text-muted-foreground bg-card/60">
            This stitch workflow definition currently has no registered DAG nodes.
          </div>
        ) : (
          <div
            style={{ width: Math.max(layout.width, 760), height: Math.max(layout.height, 240) }}
            className="relative mx-auto"
          >
            {/* Dynamic System Boundary Dividers & Two-Perimeter Bounded Corridor */}
            {layout.boundaries.map((boundary) => {
              const isSource = boundary.type === 'source-perimeter';
              const isDest = boundary.type === 'destination-perimeter';
              return (
                <div
                  key={boundary.id}
                  style={{ left: boundary.x, top: 0, height: layout.height }}
                  className={cn(
                    'pointer-events-none absolute border-l z-0',
                    isSource || isDest
                      ? 'border-primary/40 border-dashed'
                      : 'border-border/80 border-dashed',
                  )}
                >
                  <div
                    className={cn(
                      'absolute top-2 whitespace-nowrap',
                      isSource && 'left-2',
                      isDest && 'right-2 text-right',
                      !isSource && !isDest && '-translate-x-1/2',
                    )}
                  >
                    <span
                      className={cn(
                        'font-mono text-[10px] font-semibold px-2.5 py-0.5 rounded-full border shadow-xs',
                        isSource && 'bg-primary/10 border-primary/30 text-primary',
                        isDest &&
                          'bg-amber-500/10 border-amber-500/30 text-amber-600 dark:text-amber-400',
                        !isSource && !isDest && 'bg-background border-border text-muted-foreground',
                      )}
                    >
                      {boundary.label}
                    </span>
                  </div>
                </div>
              );
            })}

            {/* SVG Connecting Bezier Paths */}
            <svg
              width={Math.max(layout.width, 760)}
              height={Math.max(layout.height, 240)}
              className="pointer-events-none absolute inset-0 text-muted-foreground/60 z-0"
              aria-hidden="true"
            >
              <defs>
                {/* Arrow pointing right (LTR) */}
                <marker
                  id="dagster-arrow"
                  viewBox="0 0 10 10"
                  refX="8"
                  refY="5"
                  markerWidth="6"
                  markerHeight="6"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 1 L 10 5 L 0 9 z" fill="currentColor" />
                </marker>

                {/* Arrow pointing left (RTL) */}
                <marker
                  id="dagster-arrow-rtl"
                  viewBox="0 0 10 10"
                  refX="8"
                  refY="5"
                  markerWidth="6"
                  markerHeight="6"
                  orient="auto"
                >
                  <path d="M 0 1 L 10 5 L 0 9 z" fill="currentColor" />
                </marker>

                {/* Returning Arc Arrow (Amber) */}
                <marker
                  id="dagster-arrow-return"
                  viewBox="0 0 10 10"
                  refX="8"
                  refY="5"
                  markerWidth="6"
                  markerHeight="6"
                  orient="auto"
                >
                  <path d="M 0 1 L 10 5 L 0 9 z" className="fill-amber-500" />
                </marker>
              </defs>

              {layout.edges.map((edge) => {
                const isCross = edge.isCrossTrack;
                return (
                  <path
                    key={edge.id}
                    d={buildSvgPath(edge)}
                    fill="none"
                    strokeWidth={isCross ? 2.5 : 2}
                    strokeDasharray={
                      isCross ? '6 4' : edge.condition === 'ON_FAILURE' ? '5 4' : undefined
                    }
                    markerEnd={
                      isCross
                        ? 'url(#dagster-arrow-return)'
                        : edge.direction === 'rtl'
                          ? 'url(#dagster-arrow-rtl)'
                          : 'url(#dagster-arrow)'
                    }
                    className={cn(
                      'transition-colors',
                      isCross
                        ? 'stroke-amber-500/80 animate-pulse'
                        : 'stroke-muted-foreground/70 dark:stroke-muted-foreground/60',
                    )}
                  />
                );
              })}
            </svg>

            {/* Dynamic Dagster-Style Node Cards */}
            {layout.nodes.map((item) => {
              const node = item.node;
              const archetype = resolveNodeArchetype(node);
              const isAsyncGate = archetype === 'ASYNC_GATE';
              const isStateMutation = archetype === 'STATE_MUTATION';
              const isDataQuery = archetype === 'DATA_QUERY';
              const isSelected = activeSelectedKey === node.nodeKey;
              const stepRun = stepByNodeKey.get(node.nodeKey);

              return (
                <div
                  key={node.nodeKey}
                  style={{
                    left: item.x,
                    top: item.y,
                    width: item.width,
                    height: item.height,
                  }}
                  className="absolute z-10"
                >
                  <button
                    type="button"
                    onClick={() => handleCardClick(node)}
                    className={cn(
                      'group w-full h-full text-left rounded-xl border p-0 shadow-xs transition-all overflow-hidden flex flex-col justify-between bg-card cursor-pointer',
                      isAsyncGate &&
                        'border-dashed border-amber-500/80 bg-amber-500/5 hover:border-amber-500',
                      isStateMutation &&
                        !isAsyncGate &&
                        'border-border/80 hover:border-cyan-500/80 hover:shadow-md',
                      isDataQuery &&
                        !isAsyncGate &&
                        'border-border/80 hover:border-purple-500/80 hover:shadow-md',
                      !isAsyncGate &&
                        !isStateMutation &&
                        !isDataQuery &&
                        'border-border/80 hover:border-primary/80 hover:shadow-md',
                      isSelected && 'border-primary ring-2 ring-primary/40 shadow-md bg-accent/40',
                    )}
                  >
                    {/* Card Header Strip */}
                    <div
                      className={cn(
                        'flex items-center justify-between px-3 py-1.5 text-[10px] font-semibold border-b',
                        isAsyncGate &&
                          'bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-500/30',
                        isStateMutation &&
                          !isAsyncGate &&
                          'bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border-cyan-500/20',
                        isDataQuery &&
                          !isAsyncGate &&
                          'bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-500/20',
                        !isAsyncGate &&
                          !isStateMutation &&
                          !isDataQuery &&
                          'bg-muted/70 text-muted-foreground border-border/50',
                      )}
                    >
                      <span className="inline-flex items-center gap-1.5 uppercase tracking-wide">
                        {isAsyncGate && <Hourglass className="h-3 w-3 animate-pulse" />}
                        {isStateMutation && !isAsyncGate && <Send className="h-3 w-3" />}
                        {isDataQuery && !isAsyncGate && <Database className="h-3 w-3" />}
                        {!isAsyncGate && !isStateMutation && !isDataQuery && (
                          <Cpu className="h-3 w-3" />
                        )}
                        <span>
                          {isAsyncGate
                            ? '⚡ ASYNC GATE'
                            : isStateMutation
                              ? 'DISPATCH'
                              : isDataQuery
                                ? 'QUERY'
                                : node.kind}
                        </span>
                      </span>
                      <span className="font-mono font-normal opacity-80 text-[9px]">
                        {node.stepType.split('.').pop() || node.queueName}
                      </span>
                    </div>

                    {/* Card Body */}
                    <div className="px-3 py-2 flex flex-col justify-between flex-1">
                      <div>
                        <div className="font-mono text-xs font-semibold text-foreground truncate group-hover:text-primary transition-colors">
                          {node.nodeKey}
                        </div>
                        <div className="font-mono text-[10px] text-muted-foreground truncate mt-0.5">
                          {node.waitEventKey ? `wait_for: ${node.waitEventKey}` : node.stepType}
                        </div>
                      </div>

                      {/* Clean Card Footer: No 'PURE', No 'Configured' */}
                      <div className="flex items-center justify-between pt-1 border-t border-border/30 text-[9px] text-muted-foreground">
                        <span className="font-mono px-1 py-0.2 rounded bg-muted/60 border border-border/40 truncate max-w-[140px]">
                          {node.boundary ?? (item.track === 0 ? 'Outbound' : 'Inbound')}
                        </span>
                        {stepRun ? (
                          <StatusBadge
                            label={stepRun.status}
                            tone={mapStitchRunStatusTone(stepRun.status)}
                          />
                        ) : (
                          <span className="font-mono text-[9px] text-muted-foreground">
                            {item.track === 0 ? '→ Out' : '← In'}
                          </span>
                        )}
                      </div>
                    </div>
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
