import { Inject, Injectable } from '@nestjs/common';
import type { DbClient } from '@soopa/database';
import { and, apiTokens, eq } from '@soopa/database';
import { ApiToken } from '../../../domain/models/api-token.model.js';
import { DATABASE_CLIENT } from '../../../infrastructure/database.constants.js';
import type { IApiTokenRepository } from '../../../ports/outbound/api-token.repository.js';

@Injectable()
export class ApiTokenDrizzleRepository implements IApiTokenRepository {
  constructor(@Inject(DATABASE_CLIENT) private readonly db: DbClient) {}

  private mapToDomain(row: typeof apiTokens.$inferSelect): ApiToken {
    return new ApiToken(
      row.id,
      row.tenantId,
      row.name,
      row.clientId,
      row.secretHash,
      row.active,
      row.createdAt,
      row.lastUsedAt,
      row.expiresAt,
    );
  }

  async save(token: ApiToken): Promise<void> {
    await this.db
      .insert(apiTokens)
      .values({
        id: token.id,
        tenantId: token.tenantId,
        name: token.name,
        clientId: token.clientId,
        secretHash: token.secretHash,
        active: token.active,
        createdAt: token.createdAt,
        lastUsedAt: token.lastUsedAt,
        expiresAt: token.expiresAt,
      })
      .onConflictDoUpdate({
        target: apiTokens.id,
        set: {
          name: token.name,
          active: token.active,
          lastUsedAt: token.lastUsedAt,
          expiresAt: token.expiresAt,
        },
      });
  }

  async findById(tenantId: string, id: string): Promise<ApiToken | null> {
    const row = await this.db.query.apiTokens.findFirst({
      where: (t, { eq, and }) => and(eq(t.id, id), eq(t.tenantId, tenantId)),
    });
    if (!row) return null;
    return this.mapToDomain(row);
  }

  async findByClientId(
    tenantId: string,
    clientId: string,
  ): Promise<ApiToken | null> {
    const row = await this.db.query.apiTokens.findFirst({
      where: (t, { eq, and }) =>
        and(eq(t.clientId, clientId), eq(t.tenantId, tenantId)),
    });
    if (!row) return null;
    return this.mapToDomain(row);
  }

  async findAllByTenant(tenantId: string): Promise<ApiToken[]> {
    const rows = await this.db.query.apiTokens.findMany({
      where: (t, { eq }) => eq(t.tenantId, tenantId),
      orderBy: (t, { desc }) => [desc(t.createdAt)],
    });
    return rows.map((row) => this.mapToDomain(row));
  }

  async delete(tenantId: string, id: string): Promise<void> {
    await this.db
      .delete(apiTokens)
      .where(and(eq(apiTokens.id, id), eq(apiTokens.tenantId, tenantId)));
  }
}
