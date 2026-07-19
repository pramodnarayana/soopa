import { defineConfig } from 'drizzle-kit';
import * as dotenv from 'dotenv';

dotenv.config();

export default defineConfig({
  schema: [
    './src/schema/identity.ts',
    './src/schema/notifications.ts',
    './src/schema/scheduler.ts',
  ],
  out: './migrations',
  dialect: 'postgresql',
  dbCredentials: {
    url: process.env.DATABASE_URL || 'postgresql://user:password@localhost:5432/platform_shard_1',
  },
  verbose: true,
  strict: false,
});
