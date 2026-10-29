export type JsonPrimitive = string | number | boolean | null;
export type JsonValue =
  | JsonPrimitive
  | readonly JsonValue[]
  | { readonly [key: string]: JsonValue };
export type JsonRecord = Readonly<Record<string, unknown>>;

export const IP_PRODUCT_THEME_TOKEN = 'ip' as const;

export const AuthType = {
  OAUTH2: 'OAUTH2',
  BEARER: 'BEARER',
  API_KEY: 'API_KEY',
  BASIC: 'BASIC',
  NO_AUTH: 'NO_AUTH',
} as const;
export type AuthTypeValue = (typeof AuthType)[keyof typeof AuthType];

const AUTH_TYPE_SET: ReadonlySet<string> = new Set(Object.values(AuthType));
export function isAuthTypeValue(candidate: string): candidate is AuthTypeValue {
  return AUTH_TYPE_SET.has(candidate);
}

export const ConnectorDirection = {
  SOURCE: 'SOURCE',
  DESTINATION: 'DESTINATION',
  BIDIRECTIONAL: 'BIDIRECTIONAL',
} as const;
export type ConnectorDirectionValue =
  | (typeof ConnectorDirection)[keyof typeof ConnectorDirection]
  | (string & {});

export const ConnectionHandshakeStatus = {
  VERIFIED: 'VERIFIED',
  AUTH_FAILED: 'AUTH_FAILED',
} as const;
export type ConnectionHandshakeStatusValue =
  | (typeof ConnectionHandshakeStatus)[keyof typeof ConnectionHandshakeStatus]
  | (string & {});

export const ConnectionStatus = {
  ACTIVE: 'ACTIVE',
  AUTH_EXPIRED: 'AUTH_EXPIRED',
  DISCONNECTED: 'DISCONNECTED',
  DEACTIVATED: 'DEACTIVATED',
  SUSPENDED: 'SUSPENDED',
} as const;
export type ConnectionStatusValue =
  | (typeof ConnectionStatus)[keyof typeof ConnectionStatus]
  | (string & {});

export const SyncRunKind = {
  INCREMENTAL: 'INCREMENTAL',
  FULL_REFRESH: 'FULL_REFRESH',
} as const;
export type SyncRunKindValue = (typeof SyncRunKind)[keyof typeof SyncRunKind];

export const SyncRunStatus = {
  QUEUED: 'QUEUED',
  RUNNING: 'RUNNING',
  SUCCEEDED: 'SUCCEEDED',
  FAILED: 'FAILED',
  CANCELLED: 'CANCELLED',
} as const;
export type SyncRunStatusValue = (typeof SyncRunStatus)[keyof typeof SyncRunStatus] | (string & {});

export const TransformationMode = {
  ACTIVE: 'ACTIVE',
  SHADOW: 'SHADOW',
  DISABLED: 'DISABLED',
} as const;
export type TransformationModeValue = (typeof TransformationMode)[keyof typeof TransformationMode];

const TRANSFORMATION_MODE_SET: ReadonlySet<string> = new Set(Object.values(TransformationMode));
export function isTransformationModeValue(candidate: string): candidate is TransformationModeValue {
  return TRANSFORMATION_MODE_SET.has(candidate);
}

export const PipelineLayer = {
  L1_INGEST: 'L1_INGEST',
  L2_REPLICA: 'L2_REPLICA',
  L3_NORMALIZE: 'L3_NORMALIZE',
  L4_STITCH: 'L4_STITCH',
  L5_DELIVER: 'L5_DELIVER',
} as const;
export type PipelineLayerValue = (typeof PipelineLayer)[keyof typeof PipelineLayer];

export const ReplayStage = {
  RETRY_INGEST: 'RETRY_INGEST',
  RETRY_NORMALIZE: 'RETRY_NORMALIZE',
  RETRY_STITCH: 'RETRY_STITCH',
  RETRY_DELIVER: 'RETRY_DELIVER',
} as const;
export type ReplayStageValue = (typeof ReplayStage)[keyof typeof ReplayStage];

const REPLAY_STAGE_SET: ReadonlySet<string> = new Set(Object.values(ReplayStage));
export function isReplayStageValue(candidate: string): candidate is ReplayStageValue {
  return REPLAY_STAGE_SET.has(candidate);
}

export const ReplayDispatchStatus = {
  QUEUED: 'QUEUED',
  COMPLETED: 'COMPLETED',
  PARTIAL: 'PARTIAL',
} as const;
export type ReplayDispatchStatusValue =
  | (typeof ReplayDispatchStatus)[keyof typeof ReplayDispatchStatus]
  | (string & {});

export const TraceStatus = {
  INGESTED: 'INGESTED',
  REPLICATED: 'REPLICATED',
  NORMALIZED: 'NORMALIZED',
  DELIVERED: 'DELIVERED',
  PENDING: 'PENDING',
  RETRYING: 'RETRYING',
  FAILED: 'FAILED',
  REJECTED: 'REJECTED',
} as const;
export type TraceStatusValue = (typeof TraceStatus)[keyof typeof TraceStatus] | (string & {});

export const StitchNodeKind = {
  TASK: 'TASK',
  WAIT_FOR_EVENT: 'WAIT_FOR_EVENT',
  SLEEP: 'SLEEP',
} as const;
export type StitchNodeKindValue =
  | (typeof StitchNodeKind)[keyof typeof StitchNodeKind]
  | (string & {});

export const StitchRunStatus = {
  PENDING: 'PENDING',
  RUNNING: 'RUNNING',
  WAITING: 'WAITING',
  SUCCEEDED: 'SUCCEEDED',
  FAILED: 'FAILED',
  CANCELLED: 'CANCELLED',
} as const;
export type StitchRunStatusValue =
  | (typeof StitchRunStatus)[keyof typeof StitchRunStatus]
  | (string & {});

export const StagePosture = {
  HEALTHY: 'HEALTHY',
  WARNING: 'WARNING',
  CRITICAL: 'CRITICAL',
  SKIPPED: 'SKIPPED',
} as const;
export type StagePostureValue = (typeof StagePosture)[keyof typeof StagePosture];

export const ConnectorPropertyType = {
  SHORT_TEXT: 'shortText',
  SECRET_TEXT: 'secretText',
  NUMBER: 'number',
  BOOLEAN: 'boolean',
  DROPDOWN: 'dropdown',
  OAUTH: 'oauth',
} as const;
export type ConnectorPropertyTypeValue =
  | (typeof ConnectorPropertyType)[keyof typeof ConnectorPropertyType]
  | (string & {});
