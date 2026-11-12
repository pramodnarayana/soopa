import type { EntitySyncFromValue, EntitySyncScheduleValue, SyncRunKindValue } from './enums';

export interface ConnectionEntityField {
  readonly name: string;
  readonly dataType: string;
  readonly nullable: boolean;
  readonly description: string | null;
}

export interface ConnectionEntity {
  readonly entityId: string;
  readonly tenantId: string;
  readonly connectionId: string;
  readonly streamName: string;
  readonly syncMode: SyncRunKindValue | (string & {});
  readonly schedule: EntitySyncScheduleValue | (string & {});
  readonly syncFrom: EntitySyncFromValue | (string & {});
  readonly syncFromAt: string | null;
  readonly isEnabled: boolean;
  readonly primaryKey: readonly string[];
  readonly fields: readonly ConnectionEntityField[];
  readonly cursorField: string | null;
  readonly cursorValue: string | null;
  readonly recordsSyncedCount: number;
  readonly lastSyncedAt: string | null;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface AddConnectionEntityInput {
  readonly streamName: string;
  readonly syncMode?: SyncRunKindValue;
  readonly schedule?: EntitySyncScheduleValue;
  readonly syncFrom?: EntitySyncFromValue;
  readonly syncFromAt?: string | null;
  readonly isEnabled?: boolean;
  readonly primaryKey?: readonly string[];
  readonly fields?: readonly ConnectionEntityField[];
  readonly cursorField?: string | null;
  readonly defaultTransformationId?: string | null;
  readonly defaultTransformationVersion?: number;
}

export interface UpdateConnectionEntityInput {
  readonly syncMode?: SyncRunKindValue;
  readonly schedule?: EntitySyncScheduleValue;
  readonly syncFrom?: EntitySyncFromValue;
  readonly syncFromAt?: string | null;
  readonly isEnabled?: boolean;
}
