import type { NotificationChannelType } from '@soopa/database';
export type Channel = NotificationChannelType;

export class NotificationTemplate {
  constructor(
    public readonly eventType: string,
    public readonly channel: Channel,
    public readonly subjectTemplate: string,
    public readonly bodyTemplate: string,
  ) {}
}

export class NotificationEvent {
  constructor(
    public readonly tenantId: string,
    public readonly eventType: string,
    public readonly channels: Channel[],
    public readonly payload: Record<string, unknown>,
  ) {}
}

export class RenderedNotification {
  constructor(
    public readonly channel: Channel,
    public readonly subject: string,
    public readonly body: string,
  ) {}
}
