#!/bin/bash
set -eo pipefail

AWS_REGION="us-east-1"
echo "Logging into AWS ECR..."
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

TARGET_IMAGE="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/staging-app-image:latest"

echo "----------------------------------------"
echo "Building and Pushing: $TARGET_IMAGE"
echo "----------------------------------------"

echo "[1/3] Building image from root directory..."
docker build --platform linux/amd64 -t staging-app-image:latest ../../../../

echo "[2/3] Tagging for ECR..."
docker tag staging-app-image:latest "${TARGET_IMAGE}"

echo "[3/3] Pushing to ECR..."
docker push "${TARGET_IMAGE}"

echo "Successfully built and pushed the monorepo app image!"
