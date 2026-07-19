import { NotificationChannel, EventTypes } from "@soopa/database";
import { describe, it, expect, vi } from 'vitest';
import { DispatchNotificationUseCase } from '../src/application/DispatchNotificationUseCase.js';
import { NotificationEvent, NotificationTemplate, RenderedNotification, ChannelType } from '../src/domain/models.js';
import { NotificationRendererService, ITemplateRenderer } from '../src/domain/services.js';
import { ITemplateRepository, IDeliveryService } from '../src/ports/index.js';

class FakeTemplateRepository implements ITemplateRepository {
  public templates: NotificationTemplate[] = [];
  async getTemplates(tenantId: string, eventType: string): Promise<NotificationTemplate[]> {
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
  render(template: string, payload: Record<string, unknown>): string {
    return template + ' rendered';
  }
}

describe('DispatchNotificationUseCase', () => {
  it('should filter templates and dispatch notifications', async () => {
    const repo = new FakeTemplateRepository();
    const delivery = new FakeDeliveryService();
    const renderer = new NotificationRendererService(new FakeTemplateRenderer());

    repo.templates = [
      { id: '1', tenantId: 't1', eventType: 'EventTypes.TEST', channel: 'NotificationChannel.EMAIL', subjectTemplate: 'Sub1', bodyTemplate: 'Body1' },
      { id: '2', tenantId: 't1', eventType: 'EventTypes.TEST', channel: 'NotificationChannel.SLACK', subjectTemplate: 'Sub2', bodyTemplate: 'Body2' },
      { id: '3', tenantId: 't1', eventType: 'EventTypes.TEST', channel: 'NotificationChannel.IN_APP', subjectTemplate: 'Sub3', bodyTemplate: 'Body3' }
    ] as NotificationTemplate[];

    const useCase = new DispatchNotificationUseCase(repo, delivery, renderer);

    const event: NotificationEvent = {
      tenantId: 't1',
      eventType: 'EventTypes.TEST',
      channels: ['NotificationChannel.EMAIL', 'NotificationChannel.SLACK'] as ChannelType[],
      payload: { x: 1 }
    };

    await useCase.execute(event);

    expect(delivery.dispatched.length).toBe(2);
    expect(delivery.dispatched.map(d => d.channel)).toEqual(['NotificationChannel.EMAIL', 'NotificationChannel.SLACK']);
    expect(delivery.dispatched[0].subject).toBe('Sub1 rendered');
    expect(delivery.dispatched[0].body).toBe('Body1 rendered');
  });

  it('should do nothing if no templates match', async () => {
    const repo = new FakeTemplateRepository();
    const delivery = new FakeDeliveryService();
    const renderer = new NotificationRendererService(new FakeTemplateRenderer());

    repo.templates = [
      { id: '3', tenantId: 't1', eventType: 'EventTypes.TEST', channel: 'NotificationChannel.IN_APP', subjectTemplate: 'Sub3', bodyTemplate: 'Body3' }
    ] as NotificationTemplate[];

    const useCase = new DispatchNotificationUseCase(repo, delivery, renderer);

    const event: NotificationEvent = {
      tenantId: 't1',
      eventType: 'EventTypes.TEST',
      channels: ['NotificationChannel.EMAIL'] as ChannelType[],
      payload: { x: 1 }
    };

    await useCase.execute(event);

    expect(delivery.dispatched.length).toBe(0);
  });
});
