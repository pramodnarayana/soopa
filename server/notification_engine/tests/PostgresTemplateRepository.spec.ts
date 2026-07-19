import { NotificationChannel, EventTypes } from "@soopa/database";
import { describe, it, expect, beforeAll, beforeEach } from 'vitest';
import { PostgresTemplateRepository } from '../src/adapters/outbound/PostgresTemplateRepository.js';
import { createDbClient, notificationTemplates } from '@soopa/database';
import { InfrastructureError } from '../src/domain/errors.js';
import crypto from 'crypto';

describe('PostgresTemplateRepository', () => {
  const dbConnectionString = process.env.DATABASE_URL || 'postgres://ucp_admin:ucp_password@localhost:5434/ucp_platform';
  let repo: PostgresTemplateRepository;
  let db: ReturnType<typeof createDbClient>['db'];

  beforeAll(() => {
    repo = new PostgresTemplateRepository(dbConnectionString);
    db = createDbClient(dbConnectionString).db;
  });

  beforeEach(async () => {
    await db.delete(notificationTemplates);
  });

  it('should fetch active templates for an event type and tenant', async () => {
    const tenantId = `tenant-${crypto.randomUUID()}`;
    const eventType = EventTypes.TEST;

    await db.insert(notificationTemplates).values({
      tenantId,
      eventType,
      channel: NotificationChannel.EMAIL,
      subjectTemplate: 'Subject',
      bodyTemplate: 'Body',
      isActive: true
    });

    await db.insert(notificationTemplates).values({
      tenantId,
      eventType,
      channel: NotificationChannel.SLACK,
      subjectTemplate: 'Subject',
      bodyTemplate: 'Body',
      isActive: false
    });

    const templates = await repo.getTemplates(tenantId, eventType);

    expect(templates.length).toBe(1);
    expect(templates[0].channel).toBe(NotificationChannel.EMAIL);
    expect(templates[0].subjectTemplate).toBe('Subject');
  });

  it('should throw InfrastructureError on db failure', async () => {
    const badRepo = new PostgresTemplateRepository('postgres://bad:bad@localhost:9999/bad');
    await expect(badRepo.getTemplates('t', 'e')).rejects.toThrow(InfrastructureError);
  });
});
