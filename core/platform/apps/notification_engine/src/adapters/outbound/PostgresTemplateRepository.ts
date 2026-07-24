import { and, createDbClient, eq, notificationTemplates } from '@soopa/database';
import { InfrastructureError } from '../../domain/errors.js';
import { NotificationTemplate } from '../../domain/models.js';
import { ITemplateRepository } from '../../ports/index.js';

export class PostgresTemplateRepository implements ITemplateRepository {
  private readonly db: ReturnType<typeof createDbClient>['db'];

  constructor(connectionString: string) {
    const { db } = createDbClient(connectionString);
    this.db = db;
  }

  public async getTemplates(tenantId: string, eventType: string): Promise<NotificationTemplate[]> {
    try {
      const results = await this.db
        .select()
        .from(notificationTemplates)
        .where(
          and(
            eq(notificationTemplates.tenantId, tenantId),
            eq(notificationTemplates.eventType, eventType),
            eq(notificationTemplates.isActive, true),
          ),
        );

      return results.map(
        (row) =>
          new NotificationTemplate(eventType, row.channel, row.subjectTemplate, row.bodyTemplate),
      );
    } catch (error) {
      console.error(
        `[PostgresTemplateRepository] Failed to fetch templates for event ${eventType}`,
        error,
      );
      throw new InfrastructureError(
        `Database error while fetching templates for event ${eventType}`,
        'DB_FETCH_TEMPLATES_FAILED',
        error,
      );
    }
  }
}
