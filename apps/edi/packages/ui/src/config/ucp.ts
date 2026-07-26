/**
 * UCP (Unified Control Plane) API configuration.
 *
 * Reads from the Vite environment variable VITE_UCP_API_URL at build time.
 * Falls back to localhost:3000 for local development.
 */
export const UCP_API_URL: string =
  (import.meta.env.VITE_UCP_API_URL as string | undefined) ?? 'http://localhost:3000';
