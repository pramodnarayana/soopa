#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"
ENV=${1:-staging}

echo "=== Dynamically Fetching Configuration from Pulumi (Casdoor OIDC) [$ENV] ==="

# 1. Fetch Domain from Platform Stack
ALB_DOMAIN=$(pulumi stack output staging_domain -s "$ENV" -C "$REPO_ROOT/infra/cloud/aws/platform")
export VITE_API_PROXY_TARGET="https://api.${ALB_DOMAIN}"
export VITE_UCP_API_URL="https://api.${ALB_DOMAIN}"
export VITE_IDENTITY_API_URL="https://identity.${ALB_DOMAIN}"
export IDENTITY_API_URL="https://identity.${ALB_DOMAIN}"

# 2. Fetch Dashboard OAuth Client ID from Casdoor Stack Secrets Manager Entry
ADMIN_OAUTH_SECRET_ARN=$(pulumi stack output admin_oauth_secret_arn -s "$ENV" -C "$REPO_ROOT/infra/cloud/aws/casdoor")
IDENTITY_UCP_WEB_CLIENT_ID=$(aws secretsmanager get-secret-value \
    --secret-id "$ADMIN_OAUTH_SECRET_ARN" \
    --query "SecretString" \
    --output text | python3 -c "import json, sys; print(json.load(sys.stdin)['dashboard_client_id'])")
export VITE_IDENTITY_UCP_WEB_CLIENT_ID="$IDENTITY_UCP_WEB_CLIENT_ID"
export IDENTITY_UCP_WEB_CLIENT_ID

echo "Discovered Frontend Config: "
echo "- API Target: $VITE_API_PROXY_TARGET"
echo "- Identity URL: $VITE_IDENTITY_API_URL"

echo "=== Building Dashboard ==="
cd "$REPO_ROOT"
pnpm turbo run build --filter=@soopa/dashboard

echo "=== Fetching Dashboard S3 Bucket from Pulumi ==="
BUCKET_NAME=$(pulumi stack output dashboard_s3_bucket -s "$ENV" -C "$SCRIPT_DIR")
CLOUDFRONT_ID=$(pulumi stack output dashboard_cloudfront_id -s "$ENV" -C "$SCRIPT_DIR")

echo "=== Syncing static files to S3 ($BUCKET_NAME) ==="
# Hashed assets cached forever (immutable)
if [ -d "$REPO_ROOT/core/ucp/apps/dashboard/dist/assets" ]; then
    aws s3 sync "$REPO_ROOT/core/ucp/apps/dashboard/dist/assets" "s3://$BUCKET_NAME/assets" --cache-control "public,max-age=31536000,immutable"
fi
# HTML and root files must not be cached (always fresh entrypoint)
aws s3 sync "$REPO_ROOT/core/ucp/apps/dashboard/dist" "s3://$BUCKET_NAME" --exclude "assets/*" --cache-control "public,max-age=0,must-revalidate" --delete

echo "=== Invalidating CloudFront Cache ($CLOUDFRONT_ID) ==="
aws cloudfront create-invalidation --distribution-id "$CLOUDFRONT_ID" --paths "/*"

echo "=== Dashboard Deployment Complete ==="
DASHBOARD_URL=$(pulumi stack output dashboard_url -s "$ENV" -C "$SCRIPT_DIR")
echo "You can now visit your dashboard at: $DASHBOARD_URL"
