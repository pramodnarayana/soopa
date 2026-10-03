#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"

echo "=== Dynamically Fetching Configuration from Pulumi (The Advanced Enterprise Way) ==="

# 1. Fetch Domain from Platform Stack
cd "$REPO_ROOT/infra/cloud/aws/platform"
ALB_DOMAIN=$(pulumi stack output staging_domain -s staging)
export VITE_API_PROXY_TARGET="https://api.${ALB_DOMAIN}"
export VITE_UCP_API_URL="https://api.${ALB_DOMAIN}"
export IDENTITY_API_URL="https://identity.${ALB_DOMAIN}"

# 2. Fetch Client and Project IDs from Zitadel Config Stack
cd "$REPO_ROOT/infra/cloud/zitadel"
# Note: Since client ID is a secret, we use --show-secrets.
# Make sure your PULUMI_CONFIG_PASSPHRASE is set in your terminal!
IDENTITY_UCP_WEB_CLIENT_ID=$(pulumi stack output ucp_web_client_id -s staging --show-secrets)
export IDENTITY_UCP_WEB_CLIENT_ID
IDENTITY_UCP_PROJECT_ID=$(pulumi stack output ucp_project_id -s staging)
export IDENTITY_UCP_PROJECT_ID

echo "Discovered Frontend Config: "
echo "- API Target: $VITE_API_PROXY_TARGET"
echo "- Identity URL: $IDENTITY_API_URL"
echo "- Project ID: $IDENTITY_UCP_PROJECT_ID"

echo "=== Building Dashboard ==="
cd "$REPO_ROOT/core/ucp/apps/dashboard"
pnpm run build

echo "=== Fetching Dashboard S3 Bucket from Pulumi ==="
cd "$SCRIPT_DIR"
BUCKET_NAME=$(pulumi stack output dashboard_s3_bucket -s staging)
CLOUDFRONT_ID=$(pulumi stack output dashboard_cloudfront_id -s staging)

echo "=== Syncing static files to S3 ($BUCKET_NAME) ==="
aws s3 sync "$REPO_ROOT/core/ucp/apps/dashboard/dist/" "s3://$BUCKET_NAME/" --delete

echo "=== Invalidating CloudFront Cache ($CLOUDFRONT_ID) ==="
aws cloudfront create-invalidation --distribution-id "$CLOUDFRONT_ID" --paths "/*"

echo "=== Dashboard Deployment Complete ==="
DASHBOARD_URL=$(pulumi stack output dashboard_url -s staging)
echo "You can now visit your dashboard at: $DASHBOARD_URL"
