import { NotificationChannel } from '@soopa/database';
import { describe, expect, it } from 'vitest';
import { StrategyDeliveryDispatcher } from '../src/adapters/outbound/StrategyDeliveryDispatcher.js';
import { InfrastructureError } from '../src/domain/errors.js';
import { Channel, RenderedNotification } from '../src/domain/models.js';
import { IDeliveryService } from '../src/ports/index.js';

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

    const strategies = new Map<Channel, IDeliveryService>([
      [NotificationChannel.EMAIL, emailStrategy],
      [NotificationChannel.SLACK, slackStrategy],
    ]);

    const dispatcher = new StrategyDeliveryDispatcher(strategies);

    await dispatcher.dispatch({ channel: NotificationChannel.EMAIL } as never);
    await dispatcher.dispatch({ channel: NotificationChannel.SLACK } as never);

    expect(emailStrategy.dispatched.length).toBe(1);
    expect(slackStrategy.dispatched.length).toBe(1);
  });

  it('should throw if no strategy registered', async () => {
    const strategies = new Map<Channel, IDeliveryService>();
    const dispatcher = new StrategyDeliveryDispatcher(strategies);

    await expect(
      dispatcher.dispatch({ channel: NotificationChannel.IN_APP } as never),
    ).rejects.toThrow(InfrastructureError);
  });
});
