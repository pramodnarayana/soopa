#!/bin/bash
set -e

echo "=== Dynamically Fetching Configuration from Pulumi (The Advanced Enterprise Way) ==="

# 1. Fetch Domain from Platform Stack
cd ../../../../infra/cloud/aws/platform
ALB_DOMAIN=$(pulumi stack output staging_domain -s staging)
export VITE_API_PROXY_TARGET="https://api.${ALB_DOMAIN}"
export IDENTITY_API_URL="https://identity.${ALB_DOMAIN}"

# 2. Fetch Client and Project IDs from Zitadel Config Stack
cd ../../../../zitadel
# Note: Since client ID is a secret, we use --show-secrets.
# Make sure your PULUMI_CONFIG_PASSPHRASE is set in your terminal!
export IDENTITY_UCP_WEB_CLIENT_ID=$(pulumi stack output ucp_web_client_id -s staging --show-secrets)
export IDENTITY_UCP_PROJECT_ID=$(pulumi stack output ucp_project_id -s staging)

echo "Discovered Frontend Config: "
echo "- API Target: $VITE_API_PROXY_TARGET"
echo "- Identity URL: $IDENTITY_API_URL"
echo "- Project ID: $IDENTITY_UCP_PROJECT_ID"

echo "=== Building Dashboard ==="
cd ../../../../../core/ucp/apps/dashboard
pnpm run build

echo "=== Fetching Dashboard S3 Bucket from Pulumi ==="
cd ../../../../infra/cloud/aws/apps/dashboard
BUCKET_NAME=$(pulumi stack output dashboard_s3_bucket -s staging)

echo "=== Syncing static files to S3 ($BUCKET_NAME) ==="
aws s3 sync ../../../../../core/ucp/apps/dashboard/dist/ s3://$BUCKET_NAME/ --delete

echo "=== Dashboard Deployment Complete ==="
echo "You can now visit your dashboard at: $(pulumi stack output dashboard_url -s staging)"
