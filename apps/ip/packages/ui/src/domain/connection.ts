import type {
  AuthTypeValue,
  ConnectionHandshakeStatusValue,
  ConnectionStatusValue,
  JsonRecord,
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
}
