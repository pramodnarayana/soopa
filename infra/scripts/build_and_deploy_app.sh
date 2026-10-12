#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Ensure we hit real AWS, not LocalStack (if loaded via .env)
unset AWS_ENDPOINT_URL
unset AWS_ACCESS_KEY_ID
unset AWS_SECRET_ACCESS_KEY
unset AWS_SESSION_TOKEN
unset AWS_SECURITY_TOKEN

echo "======================================================"
echo "🚀 INITIATING MONOREPO IMAGE BUILD & DEPLOYMENT"
echo "======================================================"

ENV=${1:-staging}
AWS_REGION="us-east-1"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
GIT_SHA=$(git rev-parse --short HEAD)
ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ENV}-app-image:${GIT_SHA}"

echo "📦 Building Monorepo Docker Image..."
# Build from the root of the monorepo where the Dockerfile is located
cd "$WORKSPACE_ROOT"
docker build --platform linux/amd64 -t "$ECR_URI" -f Dockerfile .

echo "🔐 Logging into AWS ECR..."
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

echo "⬆️ Pushing Monorepo image to ECR..."
docker push "$ECR_URI"

echo "======================================================"
echo "🔄 Forcing a new deployment for all related ECS Tasks"
echo "======================================================"
SERVICES=$(aws ecs list-services --cluster "${ENV}-cluster" --query "serviceArns" --output text)
for arn in $SERVICES; do
  SERVICE_NAME=$(basename "$arn")

  # Only restart services that we know run the monorepo python app
  if [[ "$SERVICE_NAME" == *"api-server"* ]] || \
     [[ "$SERVICE_NAME" == *"ucp-workers"* ]] || \
     [[ "$SERVICE_NAME" == *"edi-dp-workers"* ]] || \
     [[ "$SERVICE_NAME" == *"edi-as2-server"* ]]; then
    echo "🔄 Restarting: $SERVICE_NAME..."
    aws ecs update-service --cluster "${ENV}-cluster" --service "$SERVICE_NAME" --force-new-deployment > /dev/null
  fi
done

echo "======================================================"
echo "✅ DEPLOYMENT TRIGGERED! The new ECS tasks are rolling out."
echo "======================================================"
