import { Webhook } from '../../domain/models/webhook.model.js';

export const WEBHOOK_REPOSITORY = 'WEBHOOK_REPOSITORY';

export interface IWebhookRepository {
  save(webhook: Webhook): Promise<void>;
  findById(tenantId: string, id: string): Promise<Webhook | null>;
  findAllByTenant(tenantId: string): Promise<Webhook[]>;
  delete(tenantId: string, id: string): Promise<void>;
}
