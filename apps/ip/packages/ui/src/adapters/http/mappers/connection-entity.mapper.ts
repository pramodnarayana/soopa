import type {
  AddConnectionEntityInput,
  ConnectionEntity,
  UpdateConnectionEntityInput,
} from '../../../domain/connection-entity';
import { EntitySyncFrom, EntitySyncSchedule, SyncRunKind } from '../../../domain/enums';
import type { ConnectionEntityWire } from '../schemas/connection-entity.schema';

export function mapConnectionEntityFromWire(wire: ConnectionEntityWire): ConnectionEntity {
  return {
    entityId: wire.entity_id,
    tenantId: wire.tenant_id,
    connectionId: wire.connection_id,
    streamName: wire.stream_name,
    syncMode: wire.sync_mode,
    schedule: wire.schedule,
    syncFrom: wire.sync_from,
    syncFromAt: wire.sync_from_at,
    isEnabled: wire.is_enabled,
    primaryKey: wire.primary_key,
    fields: wire.fields.map((field) => ({
      name: field.name,
      dataType: field.data_type,
      nullable: field.nullable,
      description: field.description,
    })),
    cursorField: wire.cursor_field,
    cursorValue: wire.cursor_value,
    recordsSyncedCount: wire.records_synced_count,
    lastSyncedAt: wire.last_synced_at,
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
  };
}

export function mapAddConnectionEntityToWire(
  input: AddConnectionEntityInput,
): Record<string, unknown> {
  return {
    stream_name: input.streamName,
    sync_mode: input.syncMode ?? SyncRunKind.INCREMENTAL,
    schedule: input.schedule ?? EntitySyncSchedule.MANUAL,
    sync_from: input.syncFrom ?? EntitySyncFrom.ALL,
    sync_from_at: input.syncFromAt ?? null,
    is_enabled: input.isEnabled ?? true,
    primary_key: input.primaryKey ?? [],
    fields: (input.fields ?? []).map((field) => ({
      name: field.name,
      data_type: field.dataType,
      nullable: field.nullable,
      description: field.description,
    })),
    cursor_field: input.cursorField ?? null,
    default_transformation_id: input.defaultTransformationId ?? null,
    default_transformation_version: input.defaultTransformationVersion ?? 1,
  };
}

export function mapUpdateConnectionEntityToWire(
  input: UpdateConnectionEntityInput,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  if (input.syncMode !== undefined) {
    payload.sync_mode = input.syncMode;
  }
  if (input.schedule !== undefined) {
    payload.schedule = input.schedule;
  }
  if (input.syncFrom !== undefined) {
    payload.sync_from = input.syncFrom;
  }
  if (input.syncFromAt !== undefined) {
    payload.sync_from_at = input.syncFromAt;
  }
  if (input.isEnabled !== undefined) {
    payload.is_enabled = input.isEnabled;
  }
  return payload;
}
