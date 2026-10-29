import type {
  CheckConnectionInput,
  Connection,
  ConnectionCheckResult,
  CreateConnectionInput,
  DiscoveredCatalog,
  RelinkConnectionInput,
} from '../../../domain/connection';
import type {
  ConnectionCheckWire,
  ConnectionWire,
  DiscoveredCatalogWire,
} from '../schemas/connection.schema';

export function mapConnectionFromWire(wire: ConnectionWire): Connection {
  return {
    id: wire.id,
    tenantId: wire.tenant_id,
    appId: wire.app_id,
    name: wire.name,
    authType: wire.auth_type,
    publicConfig: wire.public_config,
    status: wire.status,
    connectionFingerprint: wire.connection_fingerprint,
    tokenExpiresAt: wire.token_expires_at,
    lastRefreshedAt: wire.last_refreshed_at,
    lastErrorCode: wire.last_error_code,
    lastErrorMessage: wire.last_error_message,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
    deactivatedAt: wire.deactivated_at,
  };
}

export function mapConnectionCheckFromWire(wire: ConnectionCheckWire): ConnectionCheckResult {
  return {
    success: wire.success,
    status: wire.status,
    message: wire.message,
    errorCode: wire.error_code,
  };
}

export function mapDiscoveredCatalogFromWire(wire: DiscoveredCatalogWire): DiscoveredCatalog {
  return {
    connectionId: wire.connection_id,
    catalogVersion: wire.catalog_version,
    catalogHash: wire.catalog_hash,
    discoveredAt: wire.discovered_at,
    streams: wire.streams.map((stream) => ({
      name: stream.name,
      primaryKey: stream.primary_key,
      cursorField: stream.cursor_field,
      supportedSyncModes: stream.supported_sync_modes,
      fields: stream.fields.map((field) => ({
        name: field.name,
        dataType: field.data_type,
        nullable: field.nullable,
        description: field.description,
      })),
    })),
  };
}

export function mapCreateConnectionToWire(input: CreateConnectionInput): Record<string, unknown> {
  return {
    app_id: input.appId,
    name: input.name,
    auth_type: input.authType,
    public_config: input.publicConfig,
    raw_credentials: input.rawCredentials,
    endpoint_for_fingerprint: input.endpointForFingerprint ?? null,
  };
}

export function mapCheckConnectionToWire(input: CheckConnectionInput): Record<string, unknown> {
  return {
    app_id: input.appId,
    auth_type: input.authType,
    public_config: input.publicConfig,
    raw_credentials: input.rawCredentials,
  };
}

export function mapRelinkConnectionToWire(input: RelinkConnectionInput): Record<string, unknown> {
  return {
    new_name: input.newName ?? null,
    updated_raw_credentials: input.updatedRawCredentials ?? null,
  };
}
