export interface Webhook {
  id: string;
  tenantId: string;
  name: string;
  url: string;
  active: boolean;
}

export interface CreateWebhookPayload {
  name: string;
  url: string;
  authHeaderVaultRef?: string;
}

export interface UpdateWebhookPayload {
  name?: string;
  url?: string;
  active?: boolean;
}
