export interface ApiToken {
  id: string;
  name: string;
  client_id: string;
  active: boolean;
  last_used_at: string | null;
  expires_at: string | null;
  created_at: string;
}

export interface ApiTokenCreated extends ApiToken {
  token: string;
}

export interface CreateApiTokenPayload {
  name: string;
  expires_at?: string;
}
