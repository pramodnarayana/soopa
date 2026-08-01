export { and, eq, lte, sql } from 'drizzle-orm';
export * from './constants.js';
export * from './schema/index.js';

import { createId } from '@paralleldrive/cuid2';

export function generateId(prefix: string): string {
  return `${prefix}_${createId()}`;
}

import { drizzle } from 'drizzle-orm/node-postgres';
import { Pool } from 'pg';
import * as schema from './schema/index.js';

export function createDbClient(connectionString: string) {
  const pool = new Pool({ connectionString });
  const db = drizzle(pool, { schema });
  return { db, pool };
}

export type DbClient = ReturnType<typeof createDbClient>['db'];
