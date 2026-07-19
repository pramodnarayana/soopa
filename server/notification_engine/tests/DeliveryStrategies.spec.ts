import { NotificationChannel, EventTypes } from "@soopa/database";
import { describe, it, expect } from 'vitest';
import { EmailDeliveryStrategy } from '../src/adapters/outbound/channels/EmailDeliveryStrategy.js';
import { SlackDeliveryStrategy } from '../src/adapters/outbound/channels/SlackDeliveryStrategy.js';
import { InAppDeliveryStrategy } from '../src/adapters/outbound/channels/InAppDeliveryStrategy.js';

describe('Delivery Strategies', () => {
  it('EmailDeliveryStrategy should dispatch', async () => {
    const strategy = new EmailDeliveryStrategy();
    await expect(strategy.dispatch({ channel: NotificationChannel.EMAIL } as never)).resolves.toBeUndefined();
  });

  it('SlackDeliveryStrategy should dispatch', async () => {
    const strategy = new SlackDeliveryStrategy();
    await expect(strategy.dispatch({ channel: NotificationChannel.SLACK } as never)).resolves.toBeUndefined();
  });

  it('InAppDeliveryStrategy should dispatch', async () => {
    const strategy = new InAppDeliveryStrategy();
    await expect(strategy.dispatch({ channel: NotificationChannel.IN_APP } as never)).resolves.toBeUndefined();
  });
});
