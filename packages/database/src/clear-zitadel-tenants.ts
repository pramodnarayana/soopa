import * as dotenv from 'dotenv';
import * as path from 'path';

// Try loading .env from current directory, else fallback
dotenv.config({ path: path.resolve(process.cwd(), '.env') });
// Also try loading root .env if running from workspace
dotenv.config({ path: path.resolve(process.cwd(), '../../.env') });

const token = process.env.ZITADEL_API_TOKEN;
const apiUrl = process.env.ZITADEL_API_URL;

const PROTECTED_ORGS = ['ZITADEL', 'Soopa'];

async function clearZitadelTenants() {
  if (!token || !apiUrl) {
    console.error('ERROR: ZITADEL_API_TOKEN or ZITADEL_API_URL environment variable is missing.');
    process.exit(1);
  }

  console.log('Fetching organizations from Zitadel...');
  
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
    if (PROTECTED_ORGS.includes(org.name)) {
      console.log(`Skipping protected organization: ${org.name} (${org.id})`);
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

  console.log('Zitadel cleanup complete!');
}

clearZitadelTenants().catch(err => {
  console.error('Cleanup failed:', err);
  process.exit(1);
});
