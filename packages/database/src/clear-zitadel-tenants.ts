import * as dotenv from 'dotenv';
import * as path from 'path';

// Try loading .env from package root
dotenv.config({ path: path.resolve(__dirname, '../../.env') });
// Also try loading root .env if running from workspace
dotenv.config({ path: path.resolve(__dirname, '../../../.env') });

const token = process.env.ZITADEL_API_TOKEN;
const apiUrl = process.env.ZITADEL_API_URL;

// Protected organization IDs (stable identifiers)
const PROTECTED_ORG_IDS = new Set<string>([
  // Add your protected organization IDs here
]);

// Protected organization names (for logging/fallback only)
const PROTECTED_ORG_NAMES = ['ZITADEL', 'Soopa'];

// Approved local/development hosts
const APPROVED_HOSTS = [
  'localhost',
  '127.0.0.1',
  'ucp.localhost',
  'zitadel.localhost',
];

// Parse command line arguments
const args = process.argv.slice(2);
const dryRun = args.includes('--dry-run');
const force = args.includes('--force') || process.env.ZITADEL_CLEANUP_FORCE === 'true';

async function clearZitadelTenants() {
  if (!token || !apiUrl) {
    console.error('ERROR: ZITADEL_API_TOKEN or ZITADEL_API_URL environment variable is missing.');
    process.exit(1);
  }

  // Safety check: ensure we're running against a local/development environment
  const url = new URL(apiUrl);
  const isApprovedHost = APPROVED_HOSTS.some(host => url.hostname === host || url.hostname.endsWith('.' + host));

  if (!isApprovedHost && !force) {
    console.error(`ERROR: Safety check failed. API URL ${apiUrl} does not match an approved local/development host.`);
    console.error(`Approved hosts: ${APPROVED_HOSTS.join(', ')}`);
    console.error('To bypass this check, use --force flag or set ZITADEL_CLEANUP_FORCE=true environment variable.');
    process.exit(1);
  }

  if (dryRun) {
    console.log('DRY RUN MODE: No deletions will be performed.');
  }

  console.log(`Fetching organizations from Zitadel (${apiUrl})...`);
  
  let orgs: any[] = [];
  try {
    const res = await fetch(`${apiUrl}/admin/v1/orgs/_search`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
        'Accept': 'application/json',
      },
      body: JSON.stringify({})
    });

    if (!res.ok) {
      console.error('Failed to fetch orgs:', await res.text());
      process.exit(1);
    }
    
    const data = await res.json();
    orgs = data.result || [];
  } catch (err) {
    console.error('Error fetching orgs:', err);
    process.exit(1);
  }

  console.log(`Found ${orgs.length} organizations in total.`);

  for (const org of orgs) {
    // Check stable ID first, then fall back to name matching
    const isProtected = PROTECTED_ORG_IDS.has(org.id) || PROTECTED_ORG_NAMES.includes(org.name);

    if (isProtected) {
      console.log(`Skipping protected organization: ${org.name} (${org.id})`);
      continue;
    }

    if (dryRun) {
      console.log(`[DRY RUN] Would delete organization: ${org.name} (${org.id})`);
      continue;
    }

    console.log(`Deleting organization: ${org.name} (${org.id})...`);
    try {
      const res = await fetch(`${apiUrl}/admin/v1/orgs/${org.id}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Accept': 'application/json',
        },
      });

      if (!res.ok) {
        console.error(`Failed to delete org ${org.name}:`, await res.text());
      } else {
        console.log(`Successfully deleted ${org.name}`);
      }
    } catch (err) {
      console.error(`Error deleting org ${org.name}:`, err);
    }
  }

  console.log(dryRun ? 'Zitadel cleanup dry run complete!' : 'Zitadel cleanup complete!');
}

clearZitadelTenants().catch(err => {
  console.error('Cleanup failed:', err);
  process.exit(1);
});
