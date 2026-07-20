import { Global, Module } from '@nestjs/common';
import { createDbClient } from '@soopa/database';

export const DATABASE_CLIENT = Symbol('DATABASE_CLIENT');

const databaseProvider = {
  provide: DATABASE_CLIENT,
  useFactory: () => {
    const connectionString = process.env.DATABASE_URL;
    if (!connectionString) {
      throw new Error('DATABASE_URL is not set');
    }
    const { db } = createDbClient(connectionString);
    return db;
  },
};

@Global()
@Module({
  providers: [databaseProvider],
  exports: [DATABASE_CLIENT],
})
export class DatabaseModule {}
