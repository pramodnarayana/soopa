/**
 * EDI API configuration.
 *
 * Reads from the Vite environment variable VITE_EDI_API_URL at build time.
 * Falls back to localhost:8000 for local development.
 */
export const EDI_API_URL: string =
  (import.meta.env.VITE_EDI_API_URL as string | undefined) ?? 'http://localhost:8000';
