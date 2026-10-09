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

echo "📦 Building Monorepo Docker Image..."
# Build from the root of the monorepo where the Dockerfile is located
cd "$WORKSPACE_ROOT"
docker build --platform linux/amd64 -t 634680389104.dkr.ecr.us-east-1.amazonaws.com/staging-app-image:latest -f Dockerfile .

echo "🔐 Logging into AWS ECR..."
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 634680389104.dkr.ecr.us-east-1.amazonaws.com

echo "⬆️ Pushing Monorepo image to ECR..."
docker push 634680389104.dkr.ecr.us-east-1.amazonaws.com/staging-app-image:latest

echo "======================================================"
echo "🔄 Forcing a new deployment for all related ECS Tasks"
echo "======================================================"
SERVICES=$(aws ecs list-services --cluster staging-cluster --query "serviceArns" --output text)
for arn in $SERVICES; do
  SERVICE_NAME=$(basename $arn)

  # Only restart services that we know run the monorepo python app
  if [[ "$SERVICE_NAME" == *"api-server"* ]] || \
     [[ "$SERVICE_NAME" == *"ucp-workers"* ]] || \
     [[ "$SERVICE_NAME" == *"edi-dp-workers"* ]] || \
     [[ "$SERVICE_NAME" == *"edi-as2-server"* ]]; then
    echo "🔄 Restarting: $SERVICE_NAME..."
    aws ecs update-service --cluster staging-cluster --service "$SERVICE_NAME" --force-new-deployment > /dev/null
  fi
done

echo "======================================================"
echo "✅ DEPLOYMENT TRIGGERED! The new ECS tasks are rolling out."
echo "======================================================"
