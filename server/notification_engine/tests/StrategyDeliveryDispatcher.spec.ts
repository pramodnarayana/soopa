import { NotificationChannel, EventTypes } from "@soopa/database";
import { describe, it, expect, vi } from 'vitest';
import { StrategyDeliveryDispatcher } from '../src/adapters/outbound/StrategyDeliveryDispatcher.js';
import { IDeliveryService } from '../src/ports/index.js';
import { ChannelType, RenderedNotification } from '../src/domain/models.js';
import { InfrastructureError } from '../src/domain/errors.js';

class FakeStrategy implements IDeliveryService {
  public dispatched: RenderedNotification[] = [];
  async dispatch(notification: RenderedNotification): Promise<void> {
    this.dispatched.push(notification);
  }
}

describe('StrategyDeliveryDispatcher', () => {
  it('should dispatch to the correct strategy', async () => {
    const emailStrategy = new FakeStrategy();
    const slackStrategy = new FakeStrategy();

    const strategies = new Map<ChannelType, IDeliveryService>([
      [NotificationChannel.EMAIL, emailStrategy],
      [NotificationChannel.SLACK, slackStrategy]
    ]);

    const dispatcher = new StrategyDeliveryDispatcher(strategies);

    await dispatcher.dispatch({ channel: NotificationChannel.EMAIL } as never);
    await dispatcher.dispatch({ channel: NotificationChannel.SLACK } as never);

    expect(emailStrategy.dispatched.length).toBe(1);
    expect(slackStrategy.dispatched.length).toBe(1);
  });

  it('should throw if no strategy registered', async () => {
    const strategies = new Map<ChannelType, IDeliveryService>();
    const dispatcher = new StrategyDeliveryDispatcher(strategies);

    await expect(dispatcher.dispatch({ channel: NotificationChannel.IN_APP } as never)).rejects.toThrow(InfrastructureError);
  });
});
