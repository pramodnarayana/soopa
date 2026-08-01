import * as dotenv from 'dotenv';
import { defineConfig } from 'drizzle-kit';
import * as path from 'path';

dotenv.config({ path: path.resolve(process.cwd(), '../../../../.env') });

const dbUrl = process.env.DATABASE_URL;
if (!dbUrl) {
  throw new Error(
    'FATAL: DATABASE_URL environment variable is missing. ' +
    'Please ensure it is set in the .env file. Silent fallbacks are prohibited.',
  );
}

export default defineConfig({
  schema: ['./dist/schema/index.js'],
  out: './migrations',
  dialect: 'postgresql',
  dbCredentials: {
    url: dbUrl,
  },
  verbose: true,
  strict: false,
});
