/**
 * Application configuration resolved from Vite environment variables.
 *
 * This is the single, canonical place where env vars are read.
 * All modules must import from here — never access import.meta.env directly.
 */

const apiOrigin = (import.meta.env.VITE_UCP_API_URL as string | undefined)
  ?.trim()
  .replace(/\/+$/, '');

export const config = {
  apiOrigin: apiOrigin ?? '',
} as const;

export function getApiUrl(path: `/${string}`): string {
  return `${config.apiOrigin}${path}`;
}
