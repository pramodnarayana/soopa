import type { RegisterStitchInput } from './stitch';

export interface BuildRegisterStitchParams {
  readonly workflowId: string;
  readonly workflowVersion: number;
  readonly canonicalEventType: string;
  readonly isTrigger: boolean;
  readonly conditionKey: string;
  readonly idempotencyField: string;
  readonly concurrencyField: string;
}

export function buildRegisterStitchInput(
  params: BuildRegisterStitchParams,
): RegisterStitchInput | null {
  const workflowId = params.workflowId.trim();
  const canonicalEventType = params.canonicalEventType.trim();
  const idempotencyKeyField = params.idempotencyField.trim();
  if (!workflowId || !canonicalEventType || !idempotencyKeyField) {
    return null;
  }

  const trimmedCondition = params.conditionKey.trim();
  const trimmedConcurrency = params.concurrencyField.trim();

  return {
    workflowId,
    workflowVersion: params.workflowVersion,
    canonicalEventType,
    isTrigger: params.isTrigger,
    conditionEventKey: !params.isTrigger && trimmedCondition ? trimmedCondition : null,
    idempotencyKeyField,
    concurrencyKeyField: trimmedConcurrency || null,
    isActive: true,
  };
}
