#!/bin/bash
set -eo pipefail

# Enterprise Central Image Manifest Pipeline
# Usage: ./sync-images.sh [environment]

TARGET_ENV="${1:-staging}"

AWS_REGION="us-east-1"
echo "Logging into AWS ECR for environment: ${TARGET_ENV}..."
# NOTE: This call requires the sts:GetCallerIdentity IAM permission.
# Per Enterprise IaC Injection standards, prefer injecting AWS_ACCOUNT_ID as an
# env var from the pipeline rather than resolving it at runtime where feasible.
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
  "ghcr.io/zitadel/zitadel:${IDENTITY_VERSION}|${TARGET_ENV}-zitadel-image"
  "public.ecr.aws/zinclabs/openobserve:${OPENOBSERVE_VERSION}|${TARGET_ENV}-openobserve-image"
)

for ENTRY in "${IMAGES[@]}"; do
  IFS='|' read -r SOURCE_IMAGE ECR_REPO <<< "$ENTRY"

  # Extract version tag from source image
  TAG="${SOURCE_IMAGE##*:}"
  TARGET_IMAGE="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:${TAG}"

  echo "----------------------------------------"
  echo "Checking: $TARGET_IMAGE"
  echo "----------------------------------------"

  # Check if image tag already exists in private ECR to avoid redundant pulls & rate limits
  if aws ecr describe-images --repository-name "${ECR_REPO}" --image-ids imageTag="${TAG}" --region "${AWS_REGION}" >/dev/null 2>&1; then
    echo "✅ Image ${ECR_REPO}:${TAG} already exists in private ECR. Skipping sync."
    continue
  fi

  echo "Image ${ECR_REPO}:${TAG} missing from private ECR. Syncing from ${SOURCE_IMAGE}..."
  echo "[1/3] Pulling $SOURCE_IMAGE (with retry)..."
  # Retry up to 3 times with exponential back-off to handle transient registry failures.
  for attempt in 1 2 3; do
    docker pull "${SOURCE_IMAGE}" && break
    if [ "$attempt" -eq 3 ]; then
      echo "ERROR: Failed to pull ${SOURCE_IMAGE} after 3 attempts."
      exit 1
    fi
    echo "Pull attempt $attempt failed. Retrying in $((attempt * 10))s..."
    sleep $((attempt * 10))
  done

  echo "[2/3] Tagging for ECR..."
  docker tag "${SOURCE_IMAGE}" "${TARGET_IMAGE}"

  echo "[3/3] Pushing to ECR..."
  docker push "${TARGET_IMAGE}"

  echo "Successfully synced ${ECR_REPO}:${TAG}!"
done

echo "All 3rd-party images synced successfully!"
