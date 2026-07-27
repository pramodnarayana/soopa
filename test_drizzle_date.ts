import { sql } from 'drizzle-orm';
import { drizzle } from 'drizzle-orm/node-postgres';
import pkg from 'pg';

const { Client } = pkg;

import { and, eq, lte } from 'drizzle-orm';
import { scheduledJobs } from './core/ucp/packages/database/src/schema/scheduler.ts';

const TEST_JOB_ID = `diag-${Date.now()}`;

async function runInRolledBackTransaction(
  db: ReturnType<typeof drizzle>,
  label: string,
  updateFn: () => Promise<{ rowCount: number | null }>,
): Promise<void> {
  await db
    .transaction(async (tx) => {
      // Seed a uniquely identifiable test job so the update only touches this row.
      await tx.execute(
        sql`INSERT INTO scheduled_jobs (id, name, payload, status, locked_at, locked_by)
          VALUES (${TEST_JOB_ID}, 'diag-job', '{}', 'RUNNING',
                  now() - interval '1 hour', 'diag-worker')`,
      );

      let result: { rowCount: number | null };
      try {
        result = await updateFn();
      } catch (err: unknown) {
        if (err instanceof Error) {
          console.error(`[${label}] Query failed:`, err.message, '\nCause:', (err as any).cause);
        } else {
          console.error(`[${label}] Query failed with non-Error value:`, err);
        }
        throw err; // rethrow so the transaction rolls back
      }

      const affected = result.rowCount ?? 0;
      if (affected !== 1) {
        throw new Error(`[${label}] Expected 1 row affected, got ${affected}`);
      }
      console.log(`[${label}] ✓ Exactly 1 row affected — assertion passed`);

      // Always roll back: this is a diagnostic, not a real mutation.
      tx.rollback();
    })
    .catch((err: unknown) => {
      if (err instanceof Error && err.message.startsWith('[')) {
        // assertion error from inside — already logged
        return;
      }
      // rollback() itself throws; that is expected and benign
    });
}

async function main() {
  const client = new Client({
    connectionString: 'postgres://ucp_admin:ucp_password@localhost:5434/ucp_global',
  });
  await client.connect();
  const db = drizzle(client);

  const threshold = new Date();

  // Test 1: raw Date object passed to lte()
  await runInRolledBackTransaction(db, 'Date object', () =>
    db
      .update(scheduledJobs)
      .set({ status: 'PENDING', lockedAt: null, lockedBy: null })
      .where(
        and(
          eq(scheduledJobs.id, TEST_JOB_ID),
          eq(scheduledJobs.status, 'RUNNING'),
          lte(scheduledJobs.lockedAt, threshold as any),
        ),
      ),
  );

  // Test 2: ISO string cast to ::timestamp via sql template
  await runInRolledBackTransaction(db, 'ISO string ::timestamp', () =>
    db
      .update(scheduledJobs)
      .set({ status: 'PENDING', lockedAt: null, lockedBy: null })
      .where(
        and(
          eq(scheduledJobs.id, TEST_JOB_ID),
          eq(scheduledJobs.status, 'RUNNING'),
          sql`${scheduledJobs.lockedAt} <= ${threshold.toISOString()}::timestamp`,
        ),
      ),
  );

  await client.end();
}

main().catch((err: unknown) => {
  if (err instanceof Error) {
    console.error('Fatal:', err.message);
  } else {
    console.error('Fatal (non-Error):', err);
  }
  process.exit(1);
});
