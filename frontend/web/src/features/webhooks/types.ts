export interface Webhook {
  id: string;
  tenant_id?: number;
  name: string;
  type: 'WEBHOOK';
  status: 'ACTIVE' | 'INACTIVE';
  url?: string;
}

/** @deprecated Use Webhook */
export type Endpoint = Webhook;

export interface CreateWebhookEndpointPayload {
  name: string;
  url: string;
  auth_header_vault_ref?: string;
}
