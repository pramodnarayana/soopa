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
  streamName: string,
): string {
  const rawBase = (baseUrl ?? '').trim().replace(/\/+$/, '');
  const origin =
    rawBase ||
    (typeof window !== 'undefined' && window.location?.origin
      ? window.location.origin
      : 'http://localhost:8000');
  const path = `${origin}/api/v1/tenants/${encodeURIComponent(tenantId)}/ip/ingress/${encodeURIComponent(connectionId)}`;
  return `${path}?stream=${encodeURIComponent(streamName.trim())}`;
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
