import { dirname } from 'path';
import { fileURLToPath } from 'url';

/**
 * ESM-compatible replacement for __filename and __dirname.
 * CommonJS provides these as globals; ESM modules must derive them
 * from import.meta.url.
 */
export function getEsmPaths(importMetaUrl: string): {
  __filename: string;
  __dirname: string;
} {
  const __filename = fileURLToPath(importMetaUrl);
  const __dirname = dirname(__filename);
  return { __filename, __dirname };
}
