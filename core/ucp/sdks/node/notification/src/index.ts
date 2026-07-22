export type Channel = 'EMAIL' | 'SLACK' | 'IN_APP';

export interface NotificationEvent {
  eventType: string;
  channels: Channel[];
  data: Record<string, unknown>;
}

import { identityContextStorage } from '@soopa/identity';

/**
 * Dispatches a notification via the Central Control Plane.
 * The base URL is automatically resolved from the NOTIFICATION_ENGINE_URL environment variable,
 * falling back to http://localhost:3001 for local development.
 * 
 * It automatically extracts the tenantId and auth token from the current async context.
 */
export async function notify(event: NotificationEvent): Promise<void> {
  const baseUrl = process.env.NOTIFICATION_ENGINE_URL || 'http://localhost:3001';
  const url = `${baseUrl}/api/v1/notifications/send`;
  
  const state = identityContextStorage.getStore();
  const tenantId = state?.identity?.tenantId;
  const token = state?.token;

  if (!tenantId) {
    throw new Error('notify() must be called within an authenticated Identity context (missing tenantId)');
  }

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'Authorization': `Bearer ${token}` } : {})
    },
    body: JSON.stringify({ ...event, tenantId })
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`Failed to dispatch notification: ${response.status} - ${err}`);
  }
}
