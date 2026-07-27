import { drizzle } from 'drizzle-orm/node-postgres';
import pkg from 'pg';

const { Client } = pkg;

import { and, eq, lte } from 'drizzle-orm';
import { scheduledJobs } from './core/ucp/packages/database/src/schema/scheduler.ts';

async function main() {
  const client = new Client({
    connectionString: 'postgres://ucp_admin:ucp_password@localhost:5434/ucp_global',
  });
  await client.connect();
  const db = drizzle(client);

  const threshold = new Date();

  try {
    await db
      .update(scheduledJobs)
      .set({ status: 'PENDING', lockedAt: null, lockedBy: null })
      .where(
        and(eq(scheduledJobs.status, 'RUNNING'), lte(scheduledJobs.lockedAt, threshold as any)),
      );
    console.log('Success with Date');
  } catch (err) {
    console.error('Error with Date:', err.message);
  }

  try {
    await db
      .update(scheduledJobs)
      .set({ status: 'PENDING', lockedAt: null, lockedBy: null })
      .where(
        and(
          eq(scheduledJobs.status, 'RUNNING'),
          lte(scheduledJobs.lockedAt, threshold.toISOString() as any),
        ),
      );
    console.log('Success with ISO string');
  } catch (err) {
    console.error('Error with ISO string:', err.message);
  }

  await client.end();
}
main();
