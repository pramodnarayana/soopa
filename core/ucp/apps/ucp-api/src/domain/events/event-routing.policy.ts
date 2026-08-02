import { EdiEventType, UcpEventType, WebhookEventType } from '@soopa/schemas';

export enum EventRoutingScope {
  INTERNAL = 'INTERNAL',
  EXTERNAL_DATA_PLANE = 'EXTERNAL_DATA_PLANE',
}

/**
 * Enterprise Event Routing Policy
 *
 * Defines the routing scope for all domain events across the UCP.
 * - INTERNAL: Events processed only within the Control Plane (e.g. Shard Allocation).
 * - EXTERNAL_DATA_PLANE: Events replicated to all active Data Planes (e.g. EDI/IDP Shards).
 */
export const EVENT_ROUTING_POLICY: Record<string, EventRoutingScope> = {
  // --- Internal Control Plane Events ---
  [UcpEventType.APP_SUBSCRIBED]: EventRoutingScope.INTERNAL,
  [UcpEventType.APP_UNSUBSCRIBED]: EventRoutingScope.INTERNAL,
  [UcpEventType.TENANT_PROVISIONED]: EventRoutingScope.INTERNAL,
  'Idp.GrantProjectAccess': EventRoutingScope.INTERNAL,
  'Idp.RevokeProjectAccess': EventRoutingScope.INTERNAL,

  // --- Data Plane Replication Events ---
  [WebhookEventType.CREATED]: EventRoutingScope.EXTERNAL_DATA_PLANE,
  [WebhookEventType.UPDATED]: EventRoutingScope.EXTERNAL_DATA_PLANE,
  [WebhookEventType.DELETED]: EventRoutingScope.EXTERNAL_DATA_PLANE,

  // EDI specific configurations
  [EdiEventType.AS2_PARTNER_CREATED]: EventRoutingScope.EXTERNAL_DATA_PLANE,
  [EdiEventType.AS2_PARTNER_UPDATED]: EventRoutingScope.EXTERNAL_DATA_PLANE,
  [EdiEventType.AS2_PARTNER_DELETED]: EventRoutingScope.EXTERNAL_DATA_PLANE,
  [EdiEventType.INBOUND_ROUTE_CREATED]: EventRoutingScope.EXTERNAL_DATA_PLANE,
};

export function getEventRoutingScope(eventType: string): EventRoutingScope | undefined {
  return EVENT_ROUTING_POLICY[eventType];
}
