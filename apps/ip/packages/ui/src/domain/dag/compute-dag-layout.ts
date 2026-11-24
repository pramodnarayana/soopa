import type { StitchNode } from '../stitch';

export const DAG_NODE_WIDTH = 248;
export const DAG_NODE_HEIGHT = 104;
export const DAG_COLUMN_GAP = 104;
export const DAG_ROW_GAP = 36;
export const DAG_TRACK_GAP = 72;
export const DAG_CANVAS_PADDING_X = 64;
export const DAG_CANVAS_PADDING_Y = 48;

export interface DagLayoutNode {
  readonly node: StitchNode;
  readonly rank: number;
  readonly row: number;
  readonly track: number;
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
  readonly isCrossTrack: boolean;
  readonly direction: 'ltr' | 'rtl';
  readonly curveOffset?: number;
}

export interface DagBoundaryDivider {
  readonly id: string;
  readonly label: string;
  readonly x: number;
  readonly startY: number;
  readonly endY: number;
  readonly type: 'source-perimeter' | 'destination-perimeter' | 'transition';
}

export interface DagLayoutResult {
  readonly nodes: readonly DagLayoutNode[];
  readonly edges: readonly DagLayoutEdge[];
  readonly boundaries: readonly DagBoundaryDivider[];
  readonly width: number;
  readonly height: number;
}

function resolveRankInTrack(
  key: string,
  byKey: ReadonlyMap<string, StitchNode>,
  memo: Map<string, number>,
  visiting: Set<string>,
  track: number,
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
    const parentNode = byKey.get(parentKey);
    // Only resolve rank against parents within the same track
    if (parentNode && (parentNode.track ?? 0) === track) {
      const parentRank = resolveRankInTrack(parentKey, byKey, memo, visiting, track);
      if (parentRank > maxParentRank) {
        maxParentRank = parentRank;
      }
    }
  }
  visiting.delete(key);

  const computed = maxParentRank >= 0 ? maxParentRank + 1 : 0;
  memo.set(key, computed);
  return computed;
}

function buildColumnsInTrack(
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

function computeDynamicBoundaries(
  placedNodes: readonly DagLayoutNode[],
  totalHeight: number,
  sourceLineX: number,
  destLineX: number,
): DagBoundaryDivider[] {
  const boundaries: DagBoundaryDivider[] = [];
  const nodesWithBoundary = placedNodes.filter((n) => Boolean(n.node.boundary));
  if (nodesWithBoundary.length === 0) {
    return boundaries;
  }

  // 1. Resolve source boundary: earliest topological node in Track 0 (or leftmost)
  const track0NodesWithBoundary = nodesWithBoundary.filter((n) => n.track === 0);
  const sourceNode =
    track0NodesWithBoundary.sort((a, b) => a.rank - b.rank)[0] ??
    [...nodesWithBoundary].sort((a, b) => a.x - b.x)[0];
  const sourceBoundary = sourceNode.node.boundary!;

  boundaries.push({
    id: `perimeter-source-${sourceBoundary}`,
    label: sourceBoundary,
    x: sourceLineX,
    startY: 16,
    endY: totalHeight - 16,
    type: 'source-perimeter',
  });

  // 2. Resolve destination boundary: deepest topological node in Track 0 (or rightmost)
  const destNode =
    track0NodesWithBoundary.sort((a, b) => b.rank - a.rank)[0] ??
    [...nodesWithBoundary].sort((a, b) => b.x - a.x)[0];
  const destBoundary = destNode.node.boundary!;

  // If destination boundary is distinct or there are multiple boundary nodes, add destination perimeter
  if (destBoundary !== sourceBoundary || nodesWithBoundary.length > 1) {
    boundaries.push({
      id: `perimeter-dest-${destBoundary}`,
      label: destBoundary,
      x: destLineX,
      startY: 16,
      endY: totalHeight - 16,
      type: 'destination-perimeter',
    });
  }

  // 3. Resolve any intermediate boundary transitions (3 or more boundaries)
  const columnsByX = new Map<number, DagLayoutNode[]>();
  for (const node of placedNodes) {
    const colNodes = columnsByX.get(node.x) ?? [];
    colNodes.push(node);
    columnsByX.set(node.x, colNodes);
  }

  const sortedXs = [...columnsByX.keys()].sort((a, b) => a - b);
  for (let i = 0; i < sortedXs.length - 1; i++) {
    const currX = sortedXs[i];
    const nextX = sortedXs[i + 1];
    const currNodes = columnsByX.get(currX) ?? [];
    const nextNodes = columnsByX.get(nextX) ?? [];

    const currB = currNodes.find((n) => n.node.boundary)?.node.boundary;
    const nextB = nextNodes.find((n) => n.node.boundary)?.node.boundary;

    if (currB && nextB && currB !== nextB) {
      if (nextB !== destBoundary) {
        const dividerX = Math.round((currX + DAG_NODE_WIDTH + nextX) / 2);
        boundaries.push({
          id: `boundary-transition-${currB}->${nextB}`,
          label: nextB,
          x: dividerX,
          startY: 16,
          endY: totalHeight - 16,
          type: 'transition',
        });
      }
    }
  }

  return boundaries;
}

export function computeDagLayout(nodes: readonly StitchNode[]): DagLayoutResult {
  if (nodes.length === 0) {
    return { nodes: [], edges: [], boundaries: [], width: 420, height: 180 };
  }

  const byKey = new Map(nodes.map((node) => [node.nodeKey, node]));
  const track0Nodes = nodes.filter((n) => (n.track ?? 0) === 0);
  const track1Nodes = nodes.filter((n) => (n.track ?? 0) === 1);

  const isDualTrack = track1Nodes.length > 0;

  // Resolve ranks for Track 0
  const ranks0 = new Map<string, number>();
  const visiting0 = new Set<string>();
  for (const node of track0Nodes) {
    resolveRankInTrack(node.nodeKey, byKey, ranks0, visiting0, 0);
  }

  // Resolve ranks for Track 1
  const ranks1 = new Map<string, number>();
  const visiting1 = new Set<string>();
  for (const node of track1Nodes) {
    resolveRankInTrack(node.nodeKey, byKey, ranks1, visiting1, 1);
  }

  const columns0 = buildColumnsInTrack(track0Nodes, ranks0);
  const columns1 = buildColumnsInTrack(track1Nodes, ranks1);

  const maxRank0 = Math.max(0, ...ranks0.values());
  const maxRank1 = isDualTrack ? Math.max(0, ...ranks1.values()) : 0;
  const totalColumns = Math.max(maxRank0, maxRank1) + 1;

  // Track 0 rows
  let maxRows0 = 1;
  for (const colNodes of columns0.values()) {
    if (colNodes.length > maxRows0) {
      maxRows0 = colNodes.length;
    }
  }

  // Track 1 rows
  let maxRows1 = 1;
  for (const colNodes of columns1.values()) {
    if (colNodes.length > maxRows1) {
      maxRows1 = colNodes.length;
    }
  }

  const track0Height = maxRows0 * DAG_NODE_HEIGHT + Math.max(0, maxRows0 - 1) * DAG_ROW_GAP;
  const track1Height = isDualTrack
    ? maxRows1 * DAG_NODE_HEIGHT + Math.max(0, maxRows1 - 1) * DAG_ROW_GAP
    : 0;

  const totalHeight = isDualTrack
    ? DAG_CANVAS_PADDING_Y * 2 + track0Height + DAG_TRACK_GAP + track1Height
    : DAG_CANVAS_PADDING_Y * 2 + track0Height;

  const placedNodes: DagLayoutNode[] = [];
  const placedByKey = new Map<string, DagLayoutNode>();

  // 1. Place Track 0 (Left -> Right: Eastbound)
  const sortedRanks0 = [...columns0.keys()].sort((a, b) => a - b);
  for (const rank of sortedRanks0) {
    const colNodes = columns0.get(rank) ?? [];
    colNodes.forEach((node, row) => {
      const layoutNode: DagLayoutNode = {
        node,
        rank,
        row,
        track: 0,
        x: DAG_CANVAS_PADDING_X + rank * (DAG_NODE_WIDTH + DAG_COLUMN_GAP),
        y: DAG_CANVAS_PADDING_Y + row * (DAG_NODE_HEIGHT + DAG_ROW_GAP),
        width: DAG_NODE_WIDTH,
        height: DAG_NODE_HEIGHT,
      };
      placedNodes.push(layoutNode);
      placedByKey.set(node.nodeKey, layoutNode);
    });
  }

  // 2. Place Track 1 (Right -> Left: Westbound return)
  if (isDualTrack) {
    const track1BaseY = DAG_CANVAS_PADDING_Y + track0Height + DAG_TRACK_GAP;
    const sortedRanks1 = [...columns1.keys()].sort((a, b) => a - b);
    for (const rank of sortedRanks1) {
      const colNodes = columns1.get(rank) ?? [];
      // Rank 0 is placed on the far right (aligned with max column)
      // and higher ranks flow towards the left (decreasing X)
      const colIndex = totalColumns - 1 - rank;
      colNodes.forEach((node, row) => {
        const layoutNode: DagLayoutNode = {
          node,
          rank,
          row,
          track: 1,
          x: DAG_CANVAS_PADDING_X + colIndex * (DAG_NODE_WIDTH + DAG_COLUMN_GAP),
          y: track1BaseY + row * (DAG_NODE_HEIGHT + DAG_ROW_GAP),
          width: DAG_NODE_WIDTH,
          height: DAG_NODE_HEIGHT,
        };
        placedNodes.push(layoutNode);
        placedByKey.set(node.nodeKey, layoutNode);
      });
    }
  }

  // 3. Build Edges (Within-track and Cross-track returning arcs)
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

      const isCrossTrack = source.track !== target.track;
      if (isCrossTrack) {
        // Concentric U-turn: outermost row gets largest curve offset so arcs nest without intersecting
        const curveOffset = 48 + Math.max(0, maxRows0 - 1 - source.row) * 28;
        edges.push({
          id: `${parentKey}->${node.nodeKey}`,
          fromKey: parentKey,
          toKey: node.nodeKey,
          condition: node.edgeCondition,
          sourceX: source.x + source.width,
          sourceY: source.y + source.height / 2,
          targetX: target.x + target.width,
          targetY: target.y + target.height / 2,
          isCrossTrack: true,
          direction: 'ltr',
          curveOffset,
        });
      } else if (source.track === 1) {
        // Track 1 internal edge: flows Right -> Left
        edges.push({
          id: `${parentKey}->${node.nodeKey}`,
          fromKey: parentKey,
          toKey: node.nodeKey,
          condition: node.edgeCondition,
          sourceX: source.x,
          sourceY: source.y + source.height / 2,
          targetX: target.x + target.width,
          targetY: target.y + target.height / 2,
          isCrossTrack: false,
          direction: 'rtl',
        });
      } else {
        // Track 0 internal edge: flows Left -> Right
        edges.push({
          id: `${parentKey}->${node.nodeKey}`,
          fromKey: parentKey,
          toKey: node.nodeKey,
          condition: node.edgeCondition,
          sourceX: source.x + source.width,
          sourceY: source.y + source.height / 2,
          targetX: target.x,
          targetY: target.y + target.height / 2,
          isCrossTrack: false,
          direction: 'ltr',
        });
      }
    }
  }

  // 4. Two-Perimeter Bounded Corridor Calculation:
  // Source Perimeter Line on extreme left (24px)
  // Destination Perimeter Line on extreme right (beyond last node + curve offset)
  // All nodes and arcs reside strictly inside [sourceLineX, destLineX]
  const sourceLineX = 24;
  const lastColumnRightEdge =
    DAG_CANVAS_PADDING_X + (totalColumns - 1) * (DAG_NODE_WIDTH + DAG_COLUMN_GAP) + DAG_NODE_WIDTH;

  const maxCurveOffset = isDualTrack ? 48 + Math.max(0, maxRows0 - 1) * 28 : 0;
  const destLineX = lastColumnRightEdge + (isDualTrack ? maxCurveOffset + 36 : 36);
  const totalWidth = destLineX + 36;

  const boundaries = computeDynamicBoundaries(placedNodes, totalHeight, sourceLineX, destLineX);

  return {
    nodes: placedNodes,
    edges,
    boundaries,
    width: Math.max(totalWidth, 760),
    height: Math.max(totalHeight, 200),
  };
}
