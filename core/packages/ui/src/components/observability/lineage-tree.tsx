import { CornerDownRight, GitBranch } from 'lucide-react';
import React from 'react';
import { cn } from '../../lib/utils';
import { Button } from '../ui/button';
import { ReplayBadge } from './replay-badge';
import { StatusBadge, type StatusToneValue } from './status-badge';

export interface LineageTreeNode {
  readonly id: string;
  readonly parentId?: string | null;
  readonly title: string;
  readonly subtitle?: string;
  readonly statusLabel: string;
  readonly statusTone: StatusToneValue;
  readonly replayCount?: number;
  readonly timestamp?: string;
}

export interface LineageTreeProps {
  readonly nodes: readonly LineageTreeNode[];
  readonly activeNodeId: string;
  readonly onSelectNode: (nodeId: string) => void;
  readonly className?: string;
}

function computeNodeDepth(
  node: LineageTreeNode,
  byId: ReadonlyMap<string, LineageTreeNode>,
): number {
  let depth = 0;
  let cursor = node;
  const visited = new Set<string>([node.id]);

  while (cursor.parentId && byId.has(cursor.parentId) && !visited.has(cursor.parentId)) {
    visited.add(cursor.parentId);
    const parent = byId.get(cursor.parentId);
    if (!parent) break;
    depth += 1;
    cursor = parent;
  }
  return Math.min(depth, 4);
}

const DEPTH_PADDING_CLASSES: readonly string[] = ['pl-2', 'pl-6', 'pl-10', 'pl-14', 'pl-16'];

export function LineageTree({ nodes, activeNodeId, onSelectNode, className }: LineageTreeProps) {
  const byId = new Map(nodes.map((n) => [n.id, n]));

  return (
    <div
      role="navigation"
      aria-label="Trace replay attempt lineage"
      className={cn('space-y-1.5 rounded-xl border border-border bg-card p-3', className)}
    >
      <div className="mb-2 flex items-center gap-2 px-1 text-xs font-semibold tracking-wider text-muted-foreground uppercase">
        <GitBranch className="h-3.5 w-3.5" />
        <span>Attempt Lineage ({nodes.length})</span>
      </div>

      {nodes.map((node) => {
        const depth = computeNodeDepth(node, byId);
        const isCurrent = node.id === activeNodeId;

        return (
          <Button
            key={node.id}
            type="button"
            variant={isCurrent ? 'secondary' : 'ghost'}
            onClick={() => onSelectNode(node.id)}
            className={cn(
              'h-auto w-full justify-between py-2 pr-3 text-left font-normal',
              DEPTH_PADDING_CLASSES[depth] ?? 'pl-2',
              isCurrent && 'border border-primary/50 bg-accent text-accent-foreground',
            )}
          >
            <div className="flex min-w-0 items-center gap-2">
              {depth > 0 ? (
                <CornerDownRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              ) : null}
              <div className="min-w-0">
                <div className="truncate font-mono text-xs font-semibold">{node.title}</div>
                {node.subtitle ? (
                  <div className="truncate text-xs text-muted-foreground">{node.subtitle}</div>
                ) : null}
              </div>
            </div>

            <div className="ml-3 flex shrink-0 items-center gap-1.5">
              <ReplayBadge count={node.replayCount} />
              <StatusBadge label={node.statusLabel} tone={node.statusTone} />
            </div>
          </Button>
        );
      })}
    </div>
  );
}
