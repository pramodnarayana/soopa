#!/bin/bash
set -eo pipefail

AWS_REGION="us-east-1"
echo "Logging into AWS ECR..."
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

ECR_REPO_URL=$(pulumi stack output ecr_repository_url -s staging)
TARGET_IMAGE="${ECR_REPO_URL}:latest"

echo "Building App Image (this might take a minute)..."
docker build -t staging-app-image:latest -f "$REPO_ROOT/Dockerfile" "$REPO_ROOT"

echo "Tagging for ECR..."
docker tag staging-app-image:latest "${TARGET_IMAGE}"

echo "Pushing to ECR..."
docker push "${TARGET_IMAGE}"

echo "App Image pushed successfully!"
