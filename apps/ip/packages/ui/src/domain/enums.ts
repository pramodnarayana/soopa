export type JsonPrimitive = string | number | boolean | null;
export type JsonValue =
  | JsonPrimitive
  | readonly JsonValue[]
  | { readonly [key: string]: JsonValue };
export type JsonRecord = Readonly<Record<string, unknown>>;

export const IP_PRODUCT_THEME_TOKEN = 'ip' as const;
export const UNIVERSAL_SIMULATOR_APP_ID = 'universal_simulator' as const;

export const AuthType = {
  OAUTH2: 'OAUTH2',
  OAUTH2_CLIENT_CREDENTIALS: 'OAUTH2_CLIENT_CREDENTIALS',
  BEARER: 'BEARER_TOKEN',
  BEARER_TOKEN: 'BEARER_TOKEN',
  API_KEY: 'API_KEY',
  BASIC: 'BASIC_AUTH',
  BASIC_AUTH: 'BASIC_AUTH',
  NO_AUTH: 'NO_AUTH',
} as const;
export type AuthTypeValue = (typeof AuthType)[keyof typeof AuthType];

export const ApiKeyPlacement = {
  HEADER: 'HEADER',
  QUERY_PARAM: 'QUERY_PARAM',
} as const;
export type ApiKeyPlacementValue = (typeof ApiKeyPlacement)[keyof typeof ApiKeyPlacement];

export const ConnectorPropertyKey = {
  BASE_URL: 'base_url',
  AUTH_TYPE: 'auth_type',
  CHECK_PATH: 'check_path',
  TOKEN: 'token',
  PARAM_NAME: 'param_name',
  PLACEMENT: 'placement',
  USERNAME: 'username',
  PASSWORD: 'password',
  TOKEN_URL: 'token_url',
  CLIENT_ID: 'client_id',
  CLIENT_SECRET: 'client_secret',
  SCOPES: 'scopes',
  TIMEOUT_SECONDS: 'timeout_seconds',
} as const;
export type ConnectorPropertyKeyValue =
  (typeof ConnectorPropertyKey)[keyof typeof ConnectorPropertyKey];

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
  PENDING_AUTH: 'PENDING_AUTH',
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

export const EntitySyncSchedule = {
  MANUAL: 'manual',
  EVERY_5M: '5m',
  EVERY_15M: '15m',
  HOURLY: '1h',
  EVERY_6H: '6h',
  DAILY: '24h',
} as const;
export type EntitySyncScheduleValue = (typeof EntitySyncSchedule)[keyof typeof EntitySyncSchedule];

export const EntitySyncFrom = {
  ALL: 'all',
  LAST_24H: '24h',
  LAST_7D: '7d',
  LAST_30D: '30d',
  LAST_90D: '90d',
  CUSTOM: 'custom',
} as const;
export type EntitySyncFromValue = (typeof EntitySyncFrom)[keyof typeof EntitySyncFrom];

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

export const ConnectorRuntimeArchitecture = {
  DECLARATIVE_HTTP: 'DECLARATIVE_HTTP',
  GENERIC_HTTP: 'GENERIC_HTTP',
  NATIVE_PROTOCOL: 'NATIVE_PROTOCOL',
  NATIVE_SIMULATOR: 'NATIVE_SIMULATOR',
  CUSTOM_PYTHON: 'CUSTOM_PYTHON',
  PYTHON_HOOK: 'PYTHON_HOOK',
  WASM: 'WASM',
} as const;
export type ConnectorRuntimeArchitectureValue =
  | (typeof ConnectorRuntimeArchitecture)[keyof typeof ConnectorRuntimeArchitecture]
  | (string & {});

export const CatalogAppCategory = {
  API: 'API',
  CRM: 'CRM',
  BILLING: 'BILLING',
  STORAGE: 'STORAGE',
  SANDBOX: 'SANDBOX',
  ITSM: 'ITSM',
} as const;
export type CatalogAppCategoryValue =
  | (typeof CatalogAppCategory)[keyof typeof CatalogAppCategory]
  | (string & {});

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

export const BatchManifestStatus = {
  INGESTED: 'INGESTED',
  PROCESSING: 'PROCESSING',
  COMPLETED: 'COMPLETED',
  FAILED: 'FAILED',
  QUARANTINED: 'QUARANTINED',
} as const;
export type BatchManifestStatusValue =
  | (typeof BatchManifestStatus)[keyof typeof BatchManifestStatus]
  | (string & {});

export const PriorityLane = {
  P0_CRITICAL: 'P0_CRITICAL',
  P1_LIVE: 'P1_LIVE',
  P2_BULK_REPLAY: 'P2_BULK_REPLAY',
} as const;
export type PriorityLaneValue = (typeof PriorityLane)[keyof typeof PriorityLane] | (string & {});

export const CimQualityStatus = {
  VALID: 'VALID',
  ESTIMATED_VEE: 'ESTIMATED_VEE',
  ESTIMATED_MANUAL: 'ESTIMATED_MANUAL',
  DST_AMBIGUOUS: 'DST_AMBIGUOUS',
  POWER_DOWN: 'POWER_DOWN',
  QUARANTINED_SPIKE: 'QUARANTINED_SPIKE',
} as const;
export type CimQualityStatusValue =
  | (typeof CimQualityStatus)[keyof typeof CimQualityStatus]
  | (string & {});

export const TariffBucket = {
  PEAK: 'PEAK',
  SHOULDER: 'SHOULDER',
  OFF_PEAK: 'OFF_PEAK',
} as const;
export type TariffBucketValue = (typeof TariffBucket)[keyof typeof TariffBucket] | (string & {});
