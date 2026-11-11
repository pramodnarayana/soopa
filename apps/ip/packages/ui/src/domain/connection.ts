import {
  type AuthTypeValue,
  type ConnectionHandshakeStatusValue,
  ConnectionStatus,
  type ConnectionStatusValue,
  type JsonRecord,
} from './enums';

export interface Connection {
  readonly id: string;
  readonly tenantId: string;
  readonly appId: string;
  readonly name: string;
  readonly authType: AuthTypeValue | (string & {});
  readonly publicConfig: JsonRecord;
  readonly status: ConnectionStatusValue;
  readonly connectionFingerprint: string;
  readonly tokenExpiresAt: string | null;
  readonly lastRefreshedAt: string | null;
  readonly lastErrorCode: string | null;
  readonly lastErrorMessage: string | null;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly deactivatedAt: string | null;
}

export interface ConnectionCheckResult {
  readonly success: boolean;
  readonly status: ConnectionHandshakeStatusValue;
  readonly message: string | null;
  readonly errorCode: string | null;
}

export interface StreamFieldSchema {
  readonly name: string;
  readonly dataType: string;
  readonly nullable: boolean;
  readonly description: string | null;
}

export interface StreamSchema {
  readonly name: string;
  readonly fields: readonly StreamFieldSchema[];
  readonly primaryKey: readonly string[];
  readonly cursorField: string | null;
  readonly supportedSyncModes: readonly string[];
}

export interface DiscoveredCatalog {
  readonly connectionId: string;
  readonly catalogVersion: number;
  readonly catalogHash: string;
  readonly streams: readonly StreamSchema[];
  readonly discoveredAt: string;
}

export interface CreateConnectionInput {
  readonly appId: string;
  readonly name: string;
  readonly authType: AuthTypeValue;
  readonly publicConfig: JsonRecord;
  readonly rawCredentials: JsonRecord;
  readonly endpointForFingerprint?: string | null;
}

export interface CheckConnectionInput {
  readonly appId: string;
  readonly authType: AuthTypeValue;
  readonly publicConfig: JsonRecord;
  readonly rawCredentials: JsonRecord;
}

export interface RelinkConnectionInput {
  readonly newName?: string | null;
  readonly updatedRawCredentials?: JsonRecord | null;
  readonly updatedPublicConfig?: JsonRecord | null;
}

export interface UpdateConnectionInput {
  readonly newName?: string | null;
  readonly updatedRawCredentials?: JsonRecord | null;
  readonly updatedPublicConfig?: JsonRecord | null;
}

export interface SimulatePushInput {
  readonly streamName: string;
  readonly count?: number;
  readonly deliveryStyle?: 'FULL_PAYLOAD' | 'THIN_PING';
  readonly correlationId?: string | null;
}

export interface SimulatePushResult {
  readonly connectionId: string;
  readonly streamName: string;
  readonly recordsPushed: number;
  readonly recordIds: readonly string[];
  readonly traceIds: readonly string[];
  readonly status: string;
}

export function buildIngressWebhookUrl(
  baseUrl: string | undefined,
  tenantId: string,
  connectionId: string,
  streamName?: string,
): string {
  const rawBase = (baseUrl ?? '').trim().replace(/\/+$/, '');
  const origin =
    rawBase ||
    (typeof window !== 'undefined' && window.location?.origin
      ? window.location.origin
      : 'http://localhost:8000');
  const path = `${origin}/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/ingress/${encodeURIComponent(connectionId)}`;
  if (streamName && streamName.trim()) {
    return `${path}?stream=${encodeURIComponent(streamName.trim())}`;
  }
  return path;
}

export function isDeactivatedConnection(connection: Pick<Connection, 'status'>): boolean {
  return connection.status === ConnectionStatus.DEACTIVATED;
}

export function groupActiveConnectionsByApp(
  connections: readonly Connection[],
): ReadonlyMap<string, readonly Connection[]> {
  const map = new Map<string, Connection[]>();
  for (const conn of connections) {
    if (isDeactivatedConnection(conn)) {
      continue;
    }
    const existing = map.get(conn.appId);
    if (existing) {
      existing.push(conn);
    } else {
      map.set(conn.appId, [conn]);
    }
  }
  return map;
}

export const SIMULATOR_STREAM_LIMITS = {
  MIN_RECORDS_PER_PULL: 1,
  MAX_RECORDS_PER_PULL: 5_000,
  DEFAULT_RECORDS_PER_PULL: 25,
  DEFAULT_CURSOR_FIELD: 'updated_at',
} as const;

export type SimulatorBlueprintJson = JsonRecord | readonly unknown[];

export interface SimulatorEntityStreamSpec {
  readonly entityName: string;
  readonly sampleJson: SimulatorBlueprintJson;
  readonly recordsPerPull: number;
  readonly cursorField: string;
  readonly primaryKeyField?: string;
}

function isPlainRecordObject(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function clampSimulatorRecordsPerPull(rawInput: string | number): number {
  const parsed =
    typeof rawInput === 'number' ? Math.trunc(rawInput) : Number.parseInt(rawInput, 10);
  if (!Number.isFinite(parsed)) {
    return SIMULATOR_STREAM_LIMITS.DEFAULT_RECORDS_PER_PULL;
  }
  return Math.max(
    SIMULATOR_STREAM_LIMITS.MIN_RECORDS_PER_PULL,
    Math.min(SIMULATOR_STREAM_LIMITS.MAX_RECORDS_PER_PULL, parsed),
  );
}

export function buildPublicConfigWithSimulatorStream(
  existingPublicConfig: JsonRecord,
  spec: SimulatorEntityStreamSpec,
): JsonRecord {
  const existingStreamsRaw = existingPublicConfig.streams;
  const existingStreams: Record<string, unknown> = isPlainRecordObject(existingStreamsRaw)
    ? { ...existingStreamsRaw }
    : {};

  const cleanCursor = spec.cursorField.trim() || SIMULATOR_STREAM_LIMITS.DEFAULT_CURSOR_FIELD;
  const cleanPk = spec.primaryKeyField?.trim();

  const streamEntry: Record<string, unknown> = {
    sample_json: spec.sampleJson,
    records_per_pull: clampSimulatorRecordsPerPull(spec.recordsPerPull),
    cursor_field: cleanCursor,
  };
  if (cleanPk) {
    streamEntry.primary_key_field = cleanPk;
  }

  return {
    ...existingPublicConfig,
    streams: {
      ...existingStreams,
      [spec.entityName.trim()]: streamEntry,
    },
  };
}
