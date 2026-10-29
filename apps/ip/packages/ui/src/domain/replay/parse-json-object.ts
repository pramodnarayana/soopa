import type { JsonRecord } from '../enums';

export type ParsedJsonObjectResult =
  | { readonly ok: true; readonly value: JsonRecord }
  | { readonly ok: false; readonly reason: string };

export function isPlainJsonRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function parseJsonObject(raw: string): ParsedJsonObjectResult {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!isPlainJsonRecord(parsed)) {
      return { ok: false, reason: 'Modified payload must be a JSON object ({ ... }).' };
    }
    return { ok: true, value: parsed };
  } catch (err: unknown) {
    return {
      ok: false,
      reason: err instanceof Error ? err.message : 'Invalid JSON syntax.',
    };
  }
}
