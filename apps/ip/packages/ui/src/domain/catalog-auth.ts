import type { AuthTypeValue } from './enums';
import { isAuthTypeValue } from './type-guards';

export function normalizeAuthType(raw: string): AuthTypeValue | null {
  return isAuthTypeValue(raw) ? raw : null;
}
