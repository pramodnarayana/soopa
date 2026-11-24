import type { JsonRecord, StitchNodeKindValue, StitchRunStatusValue } from './enums';

export interface StitchNode {
  readonly nodeKey: string;
  readonly kind: StitchNodeKindValue;
  readonly stepType: string;
  readonly parents: readonly string[];
  readonly edgeCondition: string;
  readonly effectPolicy: string;
  readonly waitEventKey: string | null;
  readonly queueName: string;
  readonly boundary?: string | null;
  readonly track?: number;
}

export interface StitchDefinition {
  readonly workflowId: string;
  readonly version: number;
  readonly defaultPriority: string;
  readonly description: string;
  readonly nodes: readonly StitchNode[];
}

export interface Stitch {
  readonly id: string;
  readonly name?: string;
  readonly description?: string;
  readonly mappingSpecId?: string | null;
  readonly tenantId: string;
  readonly workflowId: string;
  readonly workflowVersion: number;
  readonly canonicalEventType: string;
  readonly isTrigger: boolean;
  readonly conditionEventKey: string | null;
  readonly idempotencyKeyField: string;
  readonly concurrencyKeyField: string | null;
  readonly resourceHintField: string | null;
  readonly isActive: boolean;
  readonly linkedStitchId?: string | null;
}

export interface StitchStepRun {
  readonly stepRunId: string;
  readonly nodeKey: string;
  readonly status: string;
  readonly retryCount: number;
  readonly appRetryCount: number;
  readonly internalRetryCount: number;
  readonly iterationCount: number;
  readonly failureCode: string | null;
  readonly failureDetail: string | null;
  readonly createdAt: string;
  readonly finishedAt: string | null;
}

export interface StitchRun {
  readonly runId: string;
  readonly tenantId: string;
  readonly workflowId: string;
  readonly workflowVersion: number;
  readonly status: StitchRunStatusValue;
  readonly priority: string;
  readonly concurrencyKey: string | null;
  readonly idempotencyKey: string;
  readonly traceId: string;
  readonly correlationId: string | null;
  readonly failureCode: string | null;
  readonly failureDetail: string | null;
  readonly createdAt: string;
  readonly startedAt: string | null;
  readonly finishedAt: string | null;
  readonly steps: readonly StitchStepRun[];
}

export interface TriggerStitchEventResult {
  readonly startedRunIds: readonly string[];
  readonly deduplicatedRunIds: readonly string[];
  readonly signalledStepIds: readonly string[];
}

export interface RegisterStitchInput {
  readonly stitchId?: string | null;
  readonly name?: string;
  readonly description?: string;
  readonly mappingSpecId?: string | null;
  readonly workflowId: string;
  readonly workflowVersion: number;
  readonly canonicalEventType: string;
  readonly isTrigger: boolean;
  readonly conditionEventKey?: string | null;
  readonly idempotencyKeyField: string;
  readonly concurrencyKeyField?: string | null;
  readonly resourceHintField?: string | null;
  readonly isActive: boolean;
}

export interface UpdateStitchInput {
  readonly name?: string;
  readonly description?: string;
  readonly mappingSpecId?: string | null;
  readonly filterConditions?: Record<string, unknown>;
  readonly isActive?: boolean;
}

export interface TriggerStitchEventInput {
  readonly canonicalEventType: string;
  readonly payload: JsonRecord;
  readonly eventId?: string | null;
  readonly traceId?: string | null;
  readonly correlationId?: string | null;
}

export interface ListStitchRunsFilter {
  readonly workflowId?: string;
  readonly status?: string;
  readonly traceId?: string;
  readonly limit?: number;
}

/**
 * Deterministically detects whether a Stitch workflow is transactional
 * (requiring cross-system entity reconciliation via Global Entity Map)
 * or a pure time-series streaming pipeline (stream-through directly to Kafka).
 *
 * Invariant: GEM is displayed ONLY if the stitch is transactional,
 * to show which source record is mapped to which destination record.
 */
export function isTransactionalStitch(
  stitch?: Stitch | null,
  definition?: StitchDefinition | null,
): boolean {
  if (!stitch && !definition) {
    return false;
  }

  // 1. Explicit entity mapping specification attached (GEM crosswalk enabled)
  if (stitch?.mappingSpecId) {
    return true;
  }

  // 2. Contains any TRANSACTIONAL effect policy node (e.g. state mutation, ledger write)
  if (definition?.nodes.some((n) => n.effectPolicy === 'TRANSACTIONAL')) {
    return true;
  }

  return false;
}
