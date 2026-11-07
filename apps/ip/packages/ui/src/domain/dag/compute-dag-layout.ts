import type { StitchNode } from '../stitch';

export const DAG_NODE_WIDTH = 248;
export const DAG_NODE_HEIGHT = 104;
export const DAG_COLUMN_GAP = 104;
export const DAG_ROW_GAP = 40;
export const DAG_CANVAS_PADDING_X = 36;
export const DAG_CANVAS_PADDING_Y = 36;

export interface DagLayoutNode {
  readonly node: StitchNode;
  readonly rank: number;
  readonly row: number;
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export interface DagLayoutEdge {
  readonly id: string;
  readonly fromKey: string;
  readonly toKey: string;
  readonly condition: string;
  readonly sourceX: number;
  readonly sourceY: number;
  readonly targetX: number;
  readonly targetY: number;
}

export interface DagLayoutResult {
  readonly nodes: readonly DagLayoutNode[];
  readonly edges: readonly DagLayoutEdge[];
  readonly width: number;
  readonly height: number;
}

function resolveRank(
  key: string,
  byKey: ReadonlyMap<string, StitchNode>,
  memo: Map<string, number>,
  visiting: Set<string>,
): number {
  const cached = memo.get(key);
  if (cached !== undefined) {
    return cached;
  }
  if (visiting.has(key)) {
    return 0;
  }

  const node = byKey.get(key);
  if (!node || node.parents.length === 0) {
    memo.set(key, 0);
    return 0;
  }

  visiting.add(key);
  let maxParentRank = -1;
  for (const parentKey of node.parents) {
    if (byKey.has(parentKey)) {
      const parentRank = resolveRank(parentKey, byKey, memo, visiting);
      if (parentRank > maxParentRank) {
        maxParentRank = parentRank;
      }
    }
  }
  visiting.delete(key);

  const computed = maxParentRank + 1;
  memo.set(key, computed);
  return computed;
}

function buildColumns(
  nodes: readonly StitchNode[],
  ranks: ReadonlyMap<string, number>,
): Map<number, StitchNode[]> {
  const columns = new Map<number, StitchNode[]>();
  for (const node of nodes) {
    const rank = ranks.get(node.nodeKey) ?? 0;
    const bucket = columns.get(rank) ?? [];
    bucket.push(node);
    columns.set(rank, bucket);
  }
  return columns;
}

function buildEdges(
  nodes: readonly StitchNode[],
  placedByKey: ReadonlyMap<string, DagLayoutNode>,
): DagLayoutEdge[] {
  const edges: DagLayoutEdge[] = [];
  for (const node of nodes) {
    const target = placedByKey.get(node.nodeKey);
    if (!target) {
      continue;
    }
    for (const parentKey of node.parents) {
      const source = placedByKey.get(parentKey);
      if (!source) {
        continue;
      }
      edges.push({
        id: `${parentKey}->${node.nodeKey}`,
        fromKey: parentKey,
        toKey: node.nodeKey,
        condition: node.edgeCondition,
        sourceX: source.x + source.width,
        sourceY: source.y + source.height / 2,
        targetX: target.x,
        targetY: target.y + target.height / 2,
      });
    }
  }
  return edges;
}

export function computeDagLayout(nodes: readonly StitchNode[]): DagLayoutResult {
  if (nodes.length === 0) {
    return { nodes: [], edges: [], width: 420, height: 180 };
  }

  const byKey = new Map(nodes.map((node) => [node.nodeKey, node]));
  const ranks = new Map<string, number>();
  const visiting = new Set<string>();
  for (const node of nodes) {
    resolveRank(node.nodeKey, byKey, ranks, visiting);
  }

  const columns = buildColumns(nodes, ranks);
  const placedNodes: DagLayoutNode[] = [];
  const placedByKey = new Map<string, DagLayoutNode>();
  let maxRank = 0;
  let maxRowsInColumn = 1;

  const sortedRanks = [...columns.keys()].sort((a, b) => a - b);
  for (const rank of sortedRanks) {
    if (rank > maxRank) {
      maxRank = rank;
    }
    const colNodes = columns.get(rank) ?? [];
    if (colNodes.length > maxRowsInColumn) {
      maxRowsInColumn = colNodes.length;
    }
    colNodes.forEach((node, row) => {
      const layoutNode: DagLayoutNode = {
        node,
        rank,
        row,
        x: DAG_CANVAS_PADDING_X + rank * (DAG_NODE_WIDTH + DAG_COLUMN_GAP),
        y: DAG_CANVAS_PADDING_Y + row * (DAG_NODE_HEIGHT + DAG_ROW_GAP),
        width: DAG_NODE_WIDTH,
        height: DAG_NODE_HEIGHT,
      };
      placedNodes.push(layoutNode);
      placedByKey.set(node.nodeKey, layoutNode);
    });
  }

  const width =
    DAG_CANVAS_PADDING_X * 2 + (maxRank + 1) * DAG_NODE_WIDTH + maxRank * DAG_COLUMN_GAP;
  const height =
    DAG_CANVAS_PADDING_Y * 2 +
    maxRowsInColumn * DAG_NODE_HEIGHT +
    Math.max(0, maxRowsInColumn - 1) * DAG_ROW_GAP;

  return {
    nodes: placedNodes,
    edges: buildEdges(nodes, placedByKey),
    width,
    height,
  };
}
