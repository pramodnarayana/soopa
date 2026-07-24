import { RenderedNotification } from '../../../domain/models.js';
import { IDeliveryService } from '../../../ports/index.js';

export class EmailDeliveryStrategy implements IDeliveryService {
  public async dispatch(notification: RenderedNotification): Promise<void> {
    // Enterprise-grade: integrate with @aws-sdk/client-ses here
    console.log(`[AWS SES Adapter] Sending Email. Subject: "${notification.subject}"`);
  }
}
