export { and, eq, lte, sql } from 'drizzle-orm';
export * from './constants.js';
export * from './schema/index.js';
export { generateId } from './utils/generate-id.js';


import { drizzle } from 'drizzle-orm/node-postgres';
import { Pool } from 'pg';
import * as schema from './schema/index.js';

export function createDbClient(connectionString: string) {
  const pool = new Pool({ connectionString });
  const db = drizzle(pool, { schema });
  return { db, pool };
}

export type DbClient = ReturnType<typeof createDbClient>['db'];
export type DbTransaction = Parameters<Parameters<DbClient['transaction']>[0]>[0];
