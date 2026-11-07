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
  readonly limit?: number;
}
