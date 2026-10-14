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
    set -a
    source "$WORKSPACE_ROOT/versions.env"
    set +a
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
    local SUPPORTS_IMAGE_TAG=${3:-false}
    local TARGET_DIR="$WORKSPACE_ROOT/$STACK_PATH"
    echo "------------------------------------------------------"
    echo "📦 Deploying $STACK_NAME ($ENV)..."
    echo "------------------------------------------------------"
    if ! pulumi stack select "$ENV" -C "$TARGET_DIR" 2>/dev/null; then
        pulumi stack init "$ENV" -C "$TARGET_DIR"
    fi
    if [ -n "$IMAGE_TAG" ] && [ "$SUPPORTS_IMAGE_TAG" = "true" ]; then
        pulumi config set image_tag "$IMAGE_TAG" -s "$ENV" -C "$TARGET_DIR"
    fi
    if [ -f "$TARGET_DIR/.venv/bin/activate" ]; then
        (
            source "$TARGET_DIR/.venv/bin/activate"
            pulumi refresh -y -s "$ENV" -C "$TARGET_DIR"
            pulumi up -y -s "$ENV" -C "$TARGET_DIR"
        )
    else
        pulumi refresh -y -s "$ENV" -C "$TARGET_DIR"
        pulumi up -y -s "$ENV" -C "$TARGET_DIR"
    fi
}

# Ensure required virtualenv symlinks for micro-stacks
if [ -d "$WORKSPACE_ROOT/infra/cloud/aws/.venv" ]; then
    mkdir -p "$WORKSPACE_ROOT/infra/cloud/aws/packages/seedwork"
    ln -sfn "$WORKSPACE_ROOT/infra/cloud/aws/.venv" "$WORKSPACE_ROOT/infra/cloud/aws/packages/seedwork/.venv" 2>/dev/null || true
    ln -sfn "$WORKSPACE_ROOT/infra/cloud/aws/.venv" "$WORKSPACE_ROOT/infra/.venv" 2>/dev/null || true
fi

# 1. Core Infrastructure
deploy_stack "infra/cloud/aws/foundation" "Foundation (VPC & Networking)"
deploy_stack "infra/cloud/aws/data" "Data (RDS & Secrets)"
deploy_stack "infra/cloud/aws/platform" "Platform (ECS & ECR)"
"$WORKSPACE_ROOT/infra/cloud/aws/platform/sync-images.sh" "$ENV"
deploy_stack "infra/cloud/aws/openobserve" "OpenObserve"

# 2. Core Identity Infrastructure
deploy_stack "infra/cloud/aws/zitadel" "Zitadel Infrastructure"

# 3. Identity Configuration (Pulumi Zitadel Provider)
deploy_stack "infra/cloud/zitadel" "Zitadel Configuration"

# 4. Database Migrator Task Definition & Execution
deploy_stack "infra/cloud/aws/apps/migrator" "Database Migrator" "true"
echo "------------------------------------------------------"
echo "📦 Running Database Migrations & Seeding ($ENV)..."
echo "------------------------------------------------------"
"$WORKSPACE_ROOT/infra/scripts/init_databases.sh" "$ENV"

# 5. Main API
deploy_stack "infra/cloud/aws/apps/api" "Unified API" "true"

# 4. Background Workers (UCP & EDI)
deploy_stack "infra/cloud/aws/apps/ucp/workers" "UCP Workers" "true"
deploy_stack "infra/cloud/aws/apps/edi/workers" "EDI Workers" "true"

# 5. EDI Transports & CDC
deploy_stack "infra/cloud/aws/apps/edi/as2" "EDI AS2 Server" "true"

# 6. Tools
deploy_stack "infra/cloud/aws/apps/openas2" "OpenAS2 Partner"

# 7. Frontend Dashboard
deploy_stack "infra/cloud/aws/apps/dashboard" "Frontend Dashboard"
if command -v pnpm &> /dev/null; then
    echo "------------------------------------------------------"
    echo "📦 Building & Deploying Frontend Dashboard Assets ($ENV)..."
    echo "------------------------------------------------------"
    "$WORKSPACE_ROOT/infra/cloud/aws/apps/dashboard/deploy-dashboard.sh" "$ENV"
else
    echo "⚠️ WARNING: 'pnpm' not found in PATH; skipping Frontend Dashboard asset deployment." >&2
fi

# 8. Edge & Routing
deploy_stack "infra/cloud/aws/apps/routing" "Global Edge Routing"

echo "======================================================"
echo "✅ DEPLOYMENT COMPLETE"
echo "======================================================"
