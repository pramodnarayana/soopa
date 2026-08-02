import * as dotenv from 'dotenv';
import { eq, isNull } from 'drizzle-orm';
import * as path from 'path';
import { createDbClient } from './index.js';
import { users } from './schema/identity.js';

dotenv.config({ path: path.resolve(process.cwd(), '.env') });
dotenv.config({ path: path.resolve(process.cwd(), '../../../../.env') }); // Root

const dbUrl = process.env.DATABASE_URL;
if (!dbUrl) {
  console.error('ERROR: DATABASE_URL environment variable is missing.');
  process.exit(1);
}

const { db } = createDbClient(dbUrl);

async function migrate() {
  console.log('Starting user migration...');

  // Find all users where idpUserId is null
  const usersToMigrate = await db.select().from(users).where(isNull(users.idpUserId));

  console.log(`Found ${usersToMigrate.length} users to migrate.`);

  for (const user of usersToMigrate) {
    console.log(`Migrating user: ${user.name} (ID: ${user.id})`);
    // Assuming the current 'id' is actually the Zitadel ID.
    // We will set idpUserId = id.
    // We don't HAVE to change the 'id' for existing users to a cuid because Zitadel IDs are valid primary keys.
    // We just need to populate idpUserId so the python side and webhooks can find them.
    await db.update(users).set({ idpUserId: user.id }).where(eq(users.id, user.id));

    console.log(`Successfully mapped idpUserId for user: ${user.id}`);
  }

  console.log('Migration complete.');
  process.exit(0);
}

migrate().catch((err) => {
  console.error('Migration failed:', err);
  process.exit(1);
});
