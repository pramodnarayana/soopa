import { execSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

// Paths
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const envPath = path.resolve(__dirname, '../../../../.env');

try {
  console.log('Extracting Terraform outputs from Zitadel infra...');

  // Run terraform output -json in the same directory as this script
  const tfOutputRaw = execSync('terraform output -json', {
    cwd: __dirname,
    stdio: 'pipe',
  }).toString();
  const tfOutput = JSON.parse(tfOutputRaw);

  const mappings = {
    ZITADEL_PLATFORM_ORG_ID: tfOutput.platform_org_id?.value,
    ZITADEL_UCP_PROJECT_ID: tfOutput.ucp_project_id?.value,
    ZITADEL_EDI_PROJECT_ID: tfOutput.edi_project_id?.value,
    ZITADEL_UCP_WEB_CLIENT_ID: tfOutput.ucp_web_client_id?.value,
    ZITADEL_UCP_API_CLIENT_ID: tfOutput.ucp_api_client_id?.value,
    ZITADEL_EDI_API_CLIENT_ID: tfOutput.edi_api_client_id?.value,
    ZITADEL_API_TOKEN: tfOutput.ucp_backend_pat_token?.value,
  };

  if (!fs.existsSync(envPath)) {
    console.error(`ERROR: .env file not found at ${envPath}`);
    process.exit(1);
  }

  let envContent = fs.readFileSync(envPath, 'utf8');

  // Update existing or append
  for (const [key, value] of Object.entries(mappings)) {
    if (!value) {
      console.warn(`WARNING: Missing terraform output for ${key}`);
      continue;
    }
    const regex = new RegExp(`^${key}=.*$`, 'm');
    if (regex.test(envContent)) {
      envContent = envContent.replace(regex, `${key}=${value}`);
      console.log(`Updated ${key}`);
    } else {
      envContent += `\n${key}=${value}`;
      console.log(`Added ${key}`);
    }
  }

  fs.writeFileSync(envPath, envContent);
  console.log('Successfully synchronized Terraform outputs to root .env');
} catch (err) {
  console.error('Failed to sync Zitadel environment variables:', err.message);
  process.exit(1);
}
