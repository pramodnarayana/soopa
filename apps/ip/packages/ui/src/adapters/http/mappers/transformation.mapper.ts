import type {
  BindStreamTransformationInput,
  PreviewStreamTransformationInput,
  PromoteTransformationResult,
  RegisteredTransformer,
  Transformation,
  TransformationPreviewResult,
} from '../../../domain/transformation';
import type {
  PreviewTransformationWire,
  PromoteTransformationWire,
  RegisteredTransformerWire,
  TransformationWire,
} from '../schemas/transformation.schema';

export function mapRegisteredTransformerFromWire(
  wire: RegisteredTransformerWire,
): RegisteredTransformer {
  return {
    transformationId: wire.transformation_id,
    transformationVersion: wire.transformation_version,
    targetTypes: wire.target_types,
  };
}

export function mapTransformationFromWire(wire: TransformationWire): Transformation {
  return {
    id: wire.id,
    tenantId: wire.tenant_id,
    connectionId: wire.connection_id,
    stream: wire.stream,
    transformationId: wire.transformation_id,
    transformationVersion: wire.transformation_version,
    mode: wire.mode,
    shadowTransformationVersion: wire.shadow_transformation_version,
    wasCreated: wire.was_created,
  };
}

export function mapPromoteTransformationFromWire(
  wire: PromoteTransformationWire,
): PromoteTransformationResult {
  return {
    id: wire.id,
    connectionId: wire.connection_id,
    stream: wire.stream,
    transformationId: wire.transformation_id,
    promotedVersion: wire.promoted_version,
    previousVersion: wire.previous_version,
  };
}

export function mapPreviewTransformationFromWire(
  wire: PreviewTransformationWire,
): TransformationPreviewResult {
  return {
    transformationId: wire.transformation_id,
    transformationVersion: wire.transformation_version,
    drafts: wire.drafts.map((draft) => ({
      canonicalType: draft.canonical_type,
      sourceId: draft.source_id,
      fields: draft.fields,
      extensions: draft.extensions,
      references: draft.references.map((ref) => ({
        fieldName: ref.field_name,
        targetCanonicalType: ref.target_canonical_type,
        targetSourceId: ref.target_source_id,
      })),
    })),
    rejections: wire.rejections.map((rej) => ({
      reason: rej.reason,
      fieldPath: rej.field_path,
      detail: rej.detail,
    })),
    shadowTransformationVersion: wire.shadow_transformation_version,
    shadowDiffs: wire.shadow_diffs,
  };
}

export function mapBindStreamTransformationToWire(
  input: BindStreamTransformationInput,
): Record<string, unknown> {
  return {
    transformation_id: input.transformationId,
    transformation_version: input.transformationVersion,
    mode: input.mode,
    shadow_transformation_version: input.shadowTransformationVersion ?? null,
  };
}

export function mapPreviewTransformationToWire(
  input: PreviewStreamTransformationInput,
): Record<string, unknown> {
  return {
    connection_id: input.connectionId,
    stream: input.stream,
    transformation_id: input.transformationId,
    transformation_version: input.transformationVersion,
    record_key: input.recordKey,
    sample_payload: input.samplePayload,
    shadow_transformation_version: input.shadowTransformationVersion ?? null,
  };
}
