import type {
  RegisterStitchInput,
  Stitch,
  StitchDefinition,
  StitchRun,
  TriggerStitchEventInput,
  TriggerStitchEventResult,
} from '../../../domain/stitch';
import type {
  StitchDefinitionWire,
  StitchRunWire,
  StitchWire,
  TriggerStitchEventWire,
} from '../schemas/stitch.schema';

export function mapStitchDefinitionFromWire(wire: StitchDefinitionWire): StitchDefinition {
  return {
    workflowId: wire.workflow_id,
    version: wire.version,
    defaultPriority: wire.default_priority,
    description: wire.description,
    nodes: wire.nodes.map((node) => ({
      nodeKey: node.node_key,
      kind: node.kind,
      stepType: node.step_type,
      parents: node.parents,
      edgeCondition: node.edge_condition,
      effectPolicy: node.effect_policy,
      waitEventKey: node.wait_event_key,
      queueName: node.queue_name,
    })),
  };
}

export function mapStitchFromWire(wire: StitchWire): Stitch {
  return {
    id: wire.id,
    tenantId: wire.tenant_id,
    workflowId: wire.workflow_id,
    workflowVersion: wire.workflow_version,
    canonicalEventType: wire.canonical_event_type,
    isTrigger: wire.is_trigger,
    conditionEventKey: wire.condition_event_key,
    idempotencyKeyField: wire.idempotency_key_field,
    concurrencyKeyField: wire.concurrency_key_field,
    resourceHintField: wire.resource_hint_field,
    isActive: wire.is_active,
  };
}

export function mapTriggerStitchEventFromWire(
  wire: TriggerStitchEventWire,
): TriggerStitchEventResult {
  return {
    startedRunIds: wire.started_run_ids,
    deduplicatedRunIds: wire.deduplicated_run_ids,
    signalledStepIds: wire.signalled_step_ids,
  };
}

export function mapStitchRunFromWire(wire: StitchRunWire): StitchRun {
  return {
    runId: wire.run_id,
    tenantId: wire.tenant_id,
    workflowId: wire.workflow_id,
    workflowVersion: wire.workflow_version,
    status: wire.status,
    priority: wire.priority,
    concurrencyKey: wire.concurrency_key,
    idempotencyKey: wire.idempotency_key,
    traceId: wire.trace_id,
    correlationId: wire.correlation_id,
    failureCode: wire.failure_code,
    failureDetail: wire.failure_detail,
    createdAt: wire.created_at,
    startedAt: wire.started_at,
    finishedAt: wire.finished_at,
    steps: wire.steps.map((step) => ({
      stepRunId: step.step_run_id,
      nodeKey: step.node_key,
      status: step.status,
      retryCount: step.retry_count,
      appRetryCount: step.app_retry_count,
      internalRetryCount: step.internal_retry_count,
      iterationCount: step.iteration_count,
      failureCode: step.failure_code,
      failureDetail: step.failure_detail,
      createdAt: step.created_at,
      finishedAt: step.finished_at,
    })),
  };
}

export function mapRegisterStitchToWire(input: RegisterStitchInput): Record<string, unknown> {
  return {
    stitch_id: input.stitchId ?? null,
    workflow_id: input.workflowId,
    workflow_version: input.workflowVersion,
    canonical_event_type: input.canonicalEventType,
    is_trigger: input.isTrigger,
    condition_event_key: input.conditionEventKey ?? null,
    idempotency_key_field: input.idempotencyKeyField,
    concurrency_key_field: input.concurrencyKeyField ?? null,
    resource_hint_field: input.resourceHintField ?? null,
    is_active: input.isActive,
  };
}

export function mapTriggerStitchEventToWire(
  input: TriggerStitchEventInput,
): Record<string, unknown> {
  return {
    canonical_event_type: input.canonicalEventType,
    payload: input.payload,
    event_id: input.eventId ?? null,
    trace_id: input.traceId ?? null,
    correlation_id: input.correlationId ?? null,
  };
}
