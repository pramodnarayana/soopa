import { InfrastructureError } from '../../domain/errors.js';
import { Channel, RenderedNotification } from '../../domain/models.js';
import { IDeliveryService } from '../../ports/index.js';

export class StrategyDeliveryDispatcher implements IDeliveryService {
  /**
   * Initializes the dispatcher with a registry of channel delivery strategies.
   * This implements the Strategy Pattern, adhering strictly to the Open/Closed Principle.
   */
  constructor(private readonly strategies: Map<Channel, IDeliveryService>) {}

  public async dispatch(notification: RenderedNotification): Promise<void> {
    console.log(
      `[StrategyDeliveryDispatcher] Resolving strategy for channel: ${notification.channel}`,
    );

    const strategy = this.strategies.get(notification.channel);

    if (!strategy) {
      throw new InfrastructureError(
        `No delivery strategy registered for channel: ${notification.channel}`,
        'UNSUPPORTED_DELIVERY_CHANNEL',
      );
    }

    await strategy.dispatch(notification);
  }
}
