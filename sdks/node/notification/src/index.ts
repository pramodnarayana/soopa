export type Channel = 'EMAIL' | 'SLACK' | 'IN_APP';

export interface NotificationEvent {
  tenantId: string;
  eventType: string;
  channels: Channel[];
  data: Record<string, unknown>;
}

export interface NotificationConfig {
  baseUrl: string;
  apiKey?: string;
}

export class NotificationClient {
  private baseUrl: string;

  constructor(config: NotificationConfig) {
    this.baseUrl = config.baseUrl;
  }

  /**
   * Dispatches a notification via the Central Control Plane.
   */
  public async dispatch(event: NotificationEvent): Promise<void> {
    const url = `${this.baseUrl}/api/v1/notifications/send`;
    
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(event)
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(`Failed to dispatch notification: ${response.status} - ${err}`);
    }
  }
}
