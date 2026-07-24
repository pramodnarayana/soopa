import * as dotenv from 'dotenv';
import { defineConfig } from 'drizzle-kit';
import * as path from 'path';

dotenv.config({ path: path.resolve(__dirname, '../../.env') });

export default defineConfig({
  schema: ['./src/schema/index.ts'],
  out: './migrations',
  dialect: 'postgresql',
  dbCredentials: {
    url: process.env.DATABASE_URL || 'postgresql://user:password@localhost:5432/platform_shard_1',
  },
  verbose: true,
  strict: false,
});
