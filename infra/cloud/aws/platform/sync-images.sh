#!/bin/bash
set -eo pipefail

# Enterprise Central Image Manifest Pipeline
# Usage: ./sync-images.sh

AWS_REGION="us-east-1"
echo "Logging into AWS ECR..."
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

# Parse the golden source of truth (versions.env)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
set -a
source "$SCRIPT_DIR/../../../../versions.env"
set +a

if [ -z "$IDENTITY_VERSION" ]; then
    echo "ERROR: IDENTITY_VERSION is unset in versions.env"
    exit 1
fi

if [ -z "$OPENOBSERVE_VERSION" ]; then
    echo "ERROR: OPENOBSERVE_VERSION is unset in versions.env"
    exit 1
fi
# Define images to sync. Format: "source_image|target_ecr_repo"
IMAGES=(
  "ghcr.io/zitadel/zitadel:${IDENTITY_VERSION}|staging-zitadel-image"
  "public.ecr.aws/zinclabs/openobserve:${OPENOBSERVE_VERSION}|staging-openobserve-image"
)

for ENTRY in "${IMAGES[@]}"; do
  IFS='|' read -r SOURCE_IMAGE ECR_REPO <<< "$ENTRY"

  # Extract version tag from source image
  TAG="${SOURCE_IMAGE##*:}"
  TARGET_IMAGE="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:${TAG}"

  echo "----------------------------------------"
  echo "Syncing: $SOURCE_IMAGE -> $TARGET_IMAGE"
  echo "----------------------------------------"

  echo "[1/3] Pulling $SOURCE_IMAGE..."
  docker pull "${SOURCE_IMAGE}"

  echo "[2/3] Tagging for ECR..."
  docker tag "${SOURCE_IMAGE}" "${TARGET_IMAGE}"

  echo "[3/3] Pushing to ECR..."
  docker push "${TARGET_IMAGE}"

  echo "Successfully synced ${ECR_REPO}:${TAG}!"
done

echo "All 3rd-party images synced successfully!"
