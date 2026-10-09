#!/usr/bin/env bash
set -e

# ==============================================================================
# CI/CD Deployment Script
#
# This script is strictly for use by CI/CD pipelines (e.g. GitHub Actions)
# and DevOps engineers. Application developers should NOT run this locally.
# It automatically loads versions.env and deploys all Pulumi stacks in the
# correct dependency order.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Load environment variables natively (No Node/pnpm required)
if [ -f "$WORKSPACE_ROOT/versions.env" ]; then
    export $(grep -v '^#' "$WORKSPACE_ROOT/versions.env" | xargs)
else
    echo "Error: versions.env not found!"
    exit 1
fi

if [ -z "$PULUMI_CONFIG_PASSPHRASE" ]; then
    echo "Error: PULUMI_CONFIG_PASSPHRASE must be set by the CI environment!"
    exit 1
fi

ENV=${1:-staging}

echo "======================================================"
echo "🚀 INITIATING ENTERPRISE CLOUD DEPLOYMENT FOR ENV: $ENV"
echo "======================================================"

# Helper function to deploy a stack
deploy_stack() {
    local STACK_PATH=$1
    local STACK_NAME=$2
    echo "------------------------------------------------------"
    echo "📦 Deploying $STACK_NAME ($ENV)..."
    echo "------------------------------------------------------"
    pulumi stack init $ENV -C "$WORKSPACE_ROOT/$STACK_PATH" || true
    pulumi refresh -y -s $ENV -C "$WORKSPACE_ROOT/$STACK_PATH"
    pulumi up -y -s $ENV -C "$WORKSPACE_ROOT/$STACK_PATH"
}

# 1. Core Infrastructure
deploy_stack "infra/cloud/aws/foundation" "Foundation (VPC & Networking)"
deploy_stack "infra/cloud/aws/data" "Data (RDS & Secrets)"
deploy_stack "infra/cloud/aws/platform" "Platform (ECS & ECR)"
deploy_stack "infra/cloud/aws/openobserve" "OpenObserve"

# 2. Core Identity Infrastructure
deploy_stack "infra/cloud/aws/zitadel" "Zitadel Infrastructure"

# 3. Identity Configuration (Pulumi Zitadel Provider)
deploy_stack "infra/cloud/zitadel" "Zitadel Configuration"

# 4. Database Migrator Task Definition & Execution
deploy_stack "infra/cloud/aws/apps/migrator" "Database Migrator"
echo "------------------------------------------------------"
echo "📦 Running Database Migrations & Seeding ($ENV)..."
echo "------------------------------------------------------"
$WORKSPACE_ROOT/infra/scripts/init_databases.sh $ENV

# 5. Main API
deploy_stack "infra/cloud/aws/apps/api" "Unified API"

# 4. Background Workers (UCP & EDI)
deploy_stack "infra/cloud/aws/apps/ucp/workers" "UCP Workers"
deploy_stack "infra/cloud/aws/apps/edi/workers" "EDI Workers"

# 5. EDI Transports & CDC
deploy_stack "infra/cloud/aws/apps/edi/as2" "EDI AS2 Server"

# 6. Tools
deploy_stack "infra/cloud/aws/apps/openas2" "OpenAS2 Partner"

# 7. Frontend Dashboard
deploy_stack "infra/cloud/aws/apps/dashboard" "Frontend Dashboard"

# 8. Edge & Routing
deploy_stack "infra/cloud/aws/apps/routing" "Global Edge Routing"

echo "======================================================"
echo "✅ DEPLOYMENT COMPLETE"
echo "======================================================"
