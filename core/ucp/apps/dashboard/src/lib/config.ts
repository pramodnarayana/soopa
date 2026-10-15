/**
 * Application configuration resolved from Vite environment variables.
 *
 * This is the single, canonical place where env vars are read.
 * All modules must import from here — never access import.meta.env directly.
 *
 * All required variables are validated at module evaluation time. A missing
 * variable throws immediately rather than silently producing broken API calls.
 */

const rawApiOrigin = import.meta.env.VITE_UCP_API_URL?.trim().replace(/\/+$/, '');

const identityApiUrl = import.meta.env.VITE_IDENTITY_API_URL?.trim().replace(/\/+$/, '');
const identityClientId = import.meta.env.VITE_IDENTITY_UCP_WEB_CLIENT_ID?.trim();
const identityProjectId = import.meta.env.VITE_IDENTITY_UCP_PROJECT_ID?.trim();

// Fail fast: missing required variables must throw at startup, not produce silent API failures.
if (!rawApiOrigin) {
  throw new Error(
    'FATAL: Missing required environment variable VITE_UCP_API_URL. Check the root .env file.',
  );
}

export const config = {
  apiOrigin: rawApiOrigin,
  identity: {
    authority: identityApiUrl ?? '',
    clientId: identityClientId ?? '',
    projectId: identityProjectId ?? '',
  },
} as const;

export function getApiUrl(path: `/${string}`): string {
  return `${config.apiOrigin}${path}`;
}
