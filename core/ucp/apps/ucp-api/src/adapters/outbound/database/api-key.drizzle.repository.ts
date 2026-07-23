import { Injectable, Inject } from '@nestjs/common';
import { IApiKeyRepository } from '../../../ports/outbound/api-key.repository';
import { ApiKey } from '../../../domain/models/api-key.model';
import { DATABASE_CLIENT } from '../../../infrastructure/database.module';
import { apiKeys, controlPlaneOutbox, eq } from '@soopa/database';
import type { DbClient } from '@soopa/database';
import { createId } from '@paralleldrive/cuid2';

@Injectable()
export class ApiKeyDrizzleRepository implements IApiKeyRepository {
  constructor(@Inject(DATABASE_CLIENT) private readonly db: DbClient) {}

  private mapToDomain(row: typeof apiKeys.$inferSelect): ApiKey {
    return new ApiKey(
      row.id,
      row.tenantId,
      row.name,
      row.keyHash,
      row.scopes,
      row.createdAt,
    );
  }

  async findByKeyHash(keyHash: string): Promise<ApiKey | null> {
    const [row] = await this.db
      .select()
      .from(apiKeys)
      .where(eq(apiKeys.keyHash, keyHash));
    return row ? this.mapToDomain(row) : null;
  }

  async findByTenantId(tenantId: string): Promise<ApiKey[]> {
    const rows = await this.db
      .select()
      .from(apiKeys)
      .where(eq(apiKeys.tenantId, tenantId));
    return rows.map((row) => this.mapToDomain(row));
  }

  async save(apiKey: ApiKey): Promise<ApiKey> {
    const result = await this.db.transaction(async (tx) => {
      const [row] = await tx
        .insert(apiKeys)
        .values({
          id: apiKey.id,
          tenantId: apiKey.tenantId,
          name: apiKey.name,
          keyHash: apiKey.keyHash,
          scopes: apiKey.scopes,
          createdAt: apiKey.createdAt,
        })
        .returning();

      // Process Outbox Events
      for (const event of apiKey.domainEvents) {
        await tx.insert(controlPlaneOutbox).values({
          id: createId(),
          idempotencyKey: `${event.eventName}_${apiKey.id}_${event.occurredOn.getTime()}`,
          tenantId: apiKey.tenantId,
          eventType: event.eventName,
          payload: {
            eventName: event.eventName,
            payload: event.payload,
          },
        });
      }

      return this.mapToDomain(row);
    });

    apiKey.clearEvents();
    return result;
  }

  async delete(id: string): Promise<void> {
    await this.db.delete(apiKeys).where(eq(apiKeys.id, id));
  }
}
