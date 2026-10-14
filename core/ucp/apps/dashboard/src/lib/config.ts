/**
 * Application configuration resolved from Vite environment variables.
 *
 * This is the single, canonical place where env vars are read.
 * All modules must import from here — never access import.meta.env directly.
 */

const apiOrigin = (import.meta.env.VITE_UCP_API_URL as string | undefined)
  ?.trim()
  .replace(/\/+$/, '');

const identityApiUrl = (
  (import.meta.env.VITE_IDENTITY_API_URL as string | undefined) ??
  ((import.meta.env as unknown as Record<string, string>).IDENTITY_API_URL as string | undefined)
)
  ?.trim()
  .replace(/\/+$/, '');

const identityClientId = (
  (import.meta.env.VITE_IDENTITY_UCP_WEB_CLIENT_ID as string | undefined) ??
  ((import.meta.env as unknown as Record<string, string>).IDENTITY_UCP_WEB_CLIENT_ID as
    | string
    | undefined)
)?.trim();

const identityProjectId = (
  (import.meta.env.VITE_IDENTITY_UCP_PROJECT_ID as string | undefined) ??
  ((import.meta.env as unknown as Record<string, string>).IDENTITY_UCP_PROJECT_ID as
    | string
    | undefined)
)?.trim();

export const config = {
  apiOrigin: apiOrigin ?? '',
  identity: {
    authority: identityApiUrl ?? '',
    clientId: identityClientId ?? '',
    projectId: identityProjectId ?? '',
  },
} as const;

export function getApiUrl(path: `/${string}`): string {
  return `${config.apiOrigin}${path}`;
}
