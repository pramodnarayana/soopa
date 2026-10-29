import { AuthType, type AuthTypeValue, isAuthTypeValue } from './enums';

export function normalizeAuthType(raw: string): AuthTypeValue {
  return isAuthTypeValue(raw) ? raw : AuthType.API_KEY;
}
