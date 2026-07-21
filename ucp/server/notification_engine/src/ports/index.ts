import { NotificationTemplate, RenderedNotification } from '../domain/models.js';

export interface ITemplateRepository {
  getTemplates(tenantId: string, eventType: string): Promise<NotificationTemplate[]>;
}


export interface IDeliveryService {
  dispatch(notification: RenderedNotification): Promise<void>;
}
