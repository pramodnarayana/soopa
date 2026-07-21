import { IDeliveryService } from '../../../ports/index.js';
import { RenderedNotification } from '../../../domain/models.js';

export class SlackDeliveryStrategy implements IDeliveryService {
  public async dispatch(notification: RenderedNotification): Promise<void> {
    // Enterprise-grade: integrate with Slack Webhook/Bot API here
    console.log(`[Slack Adapter] Sending message to channel. Body: "${notification.body}"`);
  }
}
