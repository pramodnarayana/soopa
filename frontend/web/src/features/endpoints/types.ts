export interface Endpoint {
  id: string;
  tenant_id?: number;
  name: string;
  type: 'WEBHOOK';
  status: 'ACTIVE' | 'INACTIVE';
}

export interface CreateWebhookEndpointPayload {
  name: string;
  url: string;
  auth_header_vault_ref?: string;
}
