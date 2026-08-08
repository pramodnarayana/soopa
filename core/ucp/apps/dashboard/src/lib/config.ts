/**
 * Application configuration resolved from Vite environment variables.
 *
 * This is the single, canonical place where env vars are read.
 * All modules must import from here — never access import.meta.env directly.
 */

const env = import.meta.env as unknown as Record<string, string>;

function optionalEnv(key: string, fallback: string): string {
  return env[key] || fallback;
}

export const config = {
  ucpApiUrl: optionalEnv('VITE_UCP_API_URL', 'http://localhost:3000').replace(/\/+$/, ''),
} as const;
