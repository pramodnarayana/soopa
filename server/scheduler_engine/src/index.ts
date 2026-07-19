import Fastify from 'fastify';
import { createDbClient } from '@soopa/database';
import { PostgresJobRepository } from './adapters/outbound/PostgresJobRepository.js';
import { SchedulerWorker } from './application/SchedulerWorker.js';

// Setup DB
const dbConnectionString = process.env.DATABASE_URL || 'postgres://ucp_admin:ucp_password@localhost:5434/ucp_platform';
const { db, pool } = createDbClient(dbConnectionString);
const jobRepository = new PostgresJobRepository(db);

// Instantiate Application Logic
const worker = new SchedulerWorker(jobRepository, 'scheduler-engine', 5000, 10);

const app = Fastify({ logger: true });

app.get('/health', async (_request, _reply) => {
  return { status: 'healthy', activeJobs: 0 }; // We can wire this to stats later
});

const start = async () => {
  try {
    await app.listen({ port: 3001, host: '0.0.0.0' });
    app.log.info('Scheduler Engine API listening on port 3001');

    // Start background loop
    app.log.info('Starting background worker loop...');
    void worker.start();
  } catch (err) {
    app.log.error(err);
    process.exit(1);
  }
};

const stop = async () => {
  app.log.info('Shutting down scheduler engine...');
  worker.stop();
  await pool.end();
  await app.close();
  process.exit(0);
};

process.on('SIGINT', () => void stop());
process.on('SIGTERM', () => void stop());

void start();
