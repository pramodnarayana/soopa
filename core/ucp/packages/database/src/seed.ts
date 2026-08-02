import * as dotenv from 'dotenv';
import * as path from 'path';
import {
  apps,
  createDbClient,
  DefaultTenants,
  databaseShards,
  EventTypes,
  generateId,
  NotificationChannel,
  notificationTemplates,
  shardRegistry,
  tenants,
  tenantUsers,
  users,
} from './index.js';
import { getEsmPaths } from './utils/esm-paths.js';

const { __dirname } = getEsmPaths(import.meta.url);

// Try loading .env from current directory, else fallback
dotenv.config({ path: path.resolve(process.cwd(), '.env') });
dotenv.config({ path: path.resolve(__dirname, '../../../../../.env') }); // Root
const dbUrl = process.env.DATABASE_URL;

if (!dbUrl) {
  console.error('ERROR: DATABASE_URL environment variable is missing.');
  process.exit(1);
}

const { db, pool } = createDbClient(dbUrl);

async function seed() {
  console.log('Seeding Notification Templates...');

  await db
    .insert(notificationTemplates)
    .values([
      {
        tenantId: DefaultTenants.SOOPA_PLATFORM,
        eventType: EventTypes.EDI_PROCESSING_FAILED,
        channel: NotificationChannel.EMAIL,
        subjectTemplate: 'Alert: EDI Processing Failed for {{partnerName}}',
        bodyTemplate:
          'The EDI payload {{fileName}} failed processing at {{time}}. Error: {{errorMessage}}',
        isActive: true,
      },
      {
        tenantId: DefaultTenants.SOOPA_PLATFORM,
        eventType: EventTypes.EDI_PROCESSING_FAILED,
        channel: NotificationChannel.SLACK,
        subjectTemplate: 'EDI Alert',
        bodyTemplate:
          '🚨 *EDI Processing Failed*\nPartner: {{partnerName}}\nFile: `{{fileName}}`\nError: {{errorMessage}}',
        isActive: true,
      },
    ])
    .onConflictDoNothing();

  console.log('Seeding Apps and Shards...');
  await db
    .insert(apps)
    .values([
      {
        id: generateId('app'),
        name: 'EDI App',
        slug: 'edi',
        description: 'B2B EDI Network',
      },
      {
        id: generateId('app'),
        name: 'IDP App',
        slug: 'idp',
        description: 'Document Processing',
      },
    ])
    .onConflictDoNothing();

  const [platformApp] = await db
    .insert(apps)
    .values({
      id: generateId('app'),
      name: 'Platform App',
      slug: 'platform',
      description: 'Soopa Platform Services',
    })
    .onConflictDoUpdate({
      target: apps.slug,
      set: { description: 'Soopa Platform Services' },
    })
    .returning();

  const [shard] = await db
    .insert(databaseShards)
    .values({
      id: generateId('shard'),
      name: 'shard_1',
      dsn: 'postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1',
    })
    .onConflictDoUpdate({
      target: databaseShards.name,
      set: { dsn: 'postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1' },
    })
    .returning();

  console.log('Seeding Master Tenant and Platform Admin...');
  const platformAdminIdpId = process.env.ZITADEL_PLATFORM_ADMIN_ID;
  const platformOrgId = process.env.ZITADEL_PLATFORM_ORG_ID;

  if (platformAdminIdpId && platformOrgId) {
    const adminUserId = generateId('usr');

    await db
      .insert(tenants)
      .values({
        id: DefaultTenants.SOOPA_PLATFORM,
        name: 'Soopa Platform',
        idpTenantId: platformOrgId,
        status: 'active',
      })
      .onConflictDoNothing();

    const [user] = await db
      .insert(users)
      .values({
        id: adminUserId,
        idpUserId: platformAdminIdpId,
        email: 'platform.admin@soopa.local',
        name: 'Platform Admin',
        status: 'active',
      })
      .onConflictDoUpdate({
        target: users.idpUserId,
        set: { status: 'active' },
      })
      .returning();

    await db
      .insert(tenantUsers)
      .values({
        tenantId: DefaultTenants.SOOPA_PLATFORM,
        userId: user.id,
        role: 'PlatformAdmin',
      })
      .onConflictDoNothing();

    await db
      .insert(shardRegistry)
      .values({
        tenantId: DefaultTenants.SOOPA_PLATFORM,
        appId: platformApp.id,
        shardId: shard.id,
      })
      .onConflictDoNothing();

    console.log('Master Tenant and Platform Admin seeded successfully.');
  } else {
    console.warn(
      'Skipping Master Tenant seed: ZITADEL_PLATFORM_ADMIN_ID or ZITADEL_PLATFORM_ORG_ID is missing.',
    );
  }

  console.log('Seeding Complete!');
  await pool.end();
  process.exit(0);
}

seed().catch((err) => {
  console.error('Seeding failed:', err);
  process.exit(1);
});
