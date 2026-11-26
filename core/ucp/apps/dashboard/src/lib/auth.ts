import { getApiUrl } from './config';

/**
 * Resolves the UCP API URL from config.
 * Defaults to the dashboard origin when VITE_UCP_API_URL is not configured.
 *
 * Authoritative identity, tenant membership, capabilities, and subscribed apps
 * are loaded exclusively from `GET /api/v1/auth/me` (never by decoding raw JWTs
 * client-side).
 */
export function getUcpApiUrl(): string {
  return getApiUrl('/api/v1');
}
