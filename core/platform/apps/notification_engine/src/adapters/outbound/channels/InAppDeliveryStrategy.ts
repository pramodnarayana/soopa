import { RenderedNotification } from '../../../domain/models.js';
import { IDeliveryService } from '../../../ports/index.js';

export class InAppDeliveryStrategy implements IDeliveryService {
  public async dispatch(notification: RenderedNotification): Promise<void> {
    // Enterprise-grade: integrate with internal Developer Portal DB / WebSocket push
    console.log(`[In-App Adapter] Saving to Inbox DB. Subject: "${notification.subject}"`);
  }
}
