import { EventTypes, NotificationChannel } from '@soopa/database';
import { describe, expect, it } from 'vitest';
import { DispatchNotificationUseCase } from '../src/application/DispatchNotificationUseCase.js';
import {
  Channel,
  NotificationEvent,
  NotificationTemplate,
  RenderedNotification,
} from '../src/domain/models.js';
import { ITemplateRenderer, NotificationRendererService } from '../src/domain/services.js';
import { IDeliveryService, ITemplateRepository } from '../src/ports/index.js';

class FakeTemplateRepository implements ITemplateRepository {
  public templates: NotificationTemplate[] = [];
  async getTemplates(_tenantId: string, _eventType: string): Promise<NotificationTemplate[]> {
    return this.templates;
  }
}

class FakeDeliveryService implements IDeliveryService {
  public dispatched: RenderedNotification[] = [];
  async dispatch(notification: RenderedNotification): Promise<void> {
    this.dispatched.push(notification);
  }
}

class FakeTemplateRenderer implements ITemplateRenderer {
  render(template: string, _payload: Record<string, unknown>): string {
    return template + ' rendered';
  }
}

describe('DispatchNotificationUseCase', () => {
  it('should filter templates and dispatch notifications', async () => {
    const repo = new FakeTemplateRepository();
    const delivery = new FakeDeliveryService();
    const renderer = new NotificationRendererService(new FakeTemplateRenderer());

    repo.templates = [
      new NotificationTemplate(EventTypes.TEST, NotificationChannel.EMAIL, 'Sub1', 'Body1'),
      new NotificationTemplate(EventTypes.TEST, NotificationChannel.SLACK, 'Sub2', 'Body2'),
      new NotificationTemplate(EventTypes.TEST, NotificationChannel.IN_APP, 'Sub3', 'Body3'),
    ];

    const useCase = new DispatchNotificationUseCase(repo, delivery, renderer);

    const event: NotificationEvent = {
      tenantId: 't1',
      eventType: EventTypes.TEST,
      channels: [NotificationChannel.EMAIL, NotificationChannel.SLACK] as Channel[],
      payload: { x: 1 },
    };

    await useCase.execute(event);

    expect(delivery.dispatched.length).toBe(2);
    expect(delivery.dispatched.map((d) => d.channel)).toEqual([
      NotificationChannel.EMAIL,
      NotificationChannel.SLACK,
    ]);
    expect(delivery.dispatched[0].subject).toBe('Sub1 rendered');
    expect(delivery.dispatched[0].body).toBe('Body1 rendered');
  });

  it('should do nothing if no templates match', async () => {
    const repo = new FakeTemplateRepository();
    const delivery = new FakeDeliveryService();
    const renderer = new NotificationRendererService(new FakeTemplateRenderer());

    repo.templates = [
      new NotificationTemplate(EventTypes.TEST, NotificationChannel.IN_APP, 'Sub3', 'Body3'),
    ];

    const useCase = new DispatchNotificationUseCase(repo, delivery, renderer);

    const event: NotificationEvent = {
      tenantId: 't1',
      eventType: EventTypes.TEST,
      channels: [NotificationChannel.EMAIL] as Channel[],
      payload: { x: 1 },
    };

    await useCase.execute(event);

    expect(delivery.dispatched.length).toBe(0);
  });
});
