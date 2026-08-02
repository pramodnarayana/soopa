import * as crypto from 'crypto';

/**
 * Generates a prefixed, URL-safe random ID.
 *
 * Format: `<prefix>_<24 hex chars>`
 *
 * Examples:
 *   generateId('ten') => 'ten_a3f8b2c1d4e5f6a7b8c9d0e1'
 *   generateId('wh')  => 'wh_1234567890abcdef12345678'
 *
 * IDs must ALWAYS be generated explicitly by the caller (domain model or use-case).
 * Schema `$defaultFn` entries are intentionally set to throw — this prevents any
 * code path from silently inserting a record without a well-formed, prefixed ID.
 */
export function generateId(prefix: string): string {
  if (!prefix || prefix.trim().length === 0) {
    throw new Error('generateId: prefix must be a non-empty string');
  }
  return `${prefix}_${crypto.randomBytes(12).toString('hex')}`;
}
