import type { JsonRecord, TransformationModeValue } from './enums';

export interface RegisteredTransformer {
  readonly transformationId: string;
  readonly transformationVersion: number;
  readonly targetTypes: readonly string[];
}

export interface Transformation {
  readonly id: string;
  readonly tenantId: string;
  readonly connectionId: string;
  readonly stream: string;
  readonly transformationId: string;
  readonly transformationVersion: number;
  readonly mode: TransformationModeValue | (string & {});
  readonly shadowTransformationVersion: number | null;
  readonly wasCreated: boolean | null;
}

export interface PromoteTransformationResult {
  readonly id: string;
  readonly connectionId: string;
  readonly stream: string;
  readonly transformationId: string;
  readonly promotedVersion: number;
  readonly previousVersion: number;
}

export interface PreviewReference {
  readonly fieldName: string;
  readonly targetCanonicalType: string;
  readonly targetSourceId: string;
}

export interface PreviewDraft {
  readonly canonicalType: string;
  readonly sourceId: string;
  readonly fields: JsonRecord;
  readonly extensions: JsonRecord;
  readonly references: readonly PreviewReference[];
}

export interface PreviewRejection {
  readonly reason: string;
  readonly fieldPath: string | null;
  readonly detail: string;
}

export interface TransformationPreviewResult {
  readonly transformationId: string;
  readonly transformationVersion: number;
  readonly drafts: readonly PreviewDraft[];
  readonly rejections: readonly PreviewRejection[];
  readonly shadowTransformationVersion: number | null;
  readonly shadowDiffs: Readonly<Record<string, JsonRecord>>;
}

export interface BindStreamTransformationInput {
  readonly transformationId: string;
  readonly transformationVersion: number;
  readonly mode: TransformationModeValue;
  readonly shadowTransformationVersion?: number | null;
}

export interface PreviewStreamTransformationInput {
  readonly connectionId: string;
  readonly stream: string;
  readonly transformationId: string;
  readonly transformationVersion: number;
  readonly recordKey: string;
  readonly samplePayload: JsonRecord;
  readonly shadowTransformationVersion?: number | null;
}
