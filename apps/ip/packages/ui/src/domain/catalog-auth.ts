import { AuthType, type AuthTypeValue } from './enums';
import { isAuthTypeValue } from './type-guards';

export function normalizeAuthType(raw: string): AuthTypeValue | null {
  const normalized = raw.trim().toUpperCase();
  switch (normalized) {
    case 'BEARER':
    case 'BEARER_TOKEN':
      return AuthType.BEARER_TOKEN;
    case 'BASIC':
    case 'BASIC_AUTH':
      return AuthType.BASIC_AUTH;
    case 'OAUTH2_CLIENT_CREDENTIALS':
      return AuthType.OAUTH2_CLIENT_CREDENTIALS;
    case 'OAUTH2':
      return AuthType.OAUTH2;
    case 'API_KEY':
      return AuthType.API_KEY;
    case 'NO_AUTH':
    case 'NONE':
      return AuthType.NO_AUTH;
    default:
      return isAuthTypeValue(raw) ? raw : null;
  }
}
