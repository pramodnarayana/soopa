import * as dotenv from 'dotenv';
import * as path from 'path';
import { fileURLToPath } from 'url';
import {
  apps,
  createDbClient,
  DefaultTenants,
  EventTypes,
  NotificationChannel,
  notificationTemplates,
} from './index.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Try loading .env from current directory, else fallback
dotenv.config({ path: path.resolve(process.cwd(), '.env') });
dotenv.config({ path: path.resolve(__dirname, '../../../../.env') }); // Root
dotenv.config({ path: path.resolve(__dirname, '../../../.env') }); // ucp/
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

  console.log('Seeding Apps...');
  await db
    .insert(apps)
    .values([
      {
        id: 'app_edi_123',
        name: 'EDI App',
        slug: 'edi',
        description: 'B2B EDI Network',
      },
      {
        id: 'app_idp_123',
        name: 'IDP App',
        slug: 'idp',
        description: 'Document Processing',
      },
    ])
    .onConflictDoNothing();

  console.log('Seeding Complete!');
  await pool.end();
  process.exit(0);
}

seed().catch((err) => {
  console.error('Seeding failed:', err);
  process.exit(1);
});
