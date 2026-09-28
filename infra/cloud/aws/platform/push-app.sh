#!/bin/bash
set -eo pipefail

AWS_REGION="us-east-1"
echo "Logging into AWS ECR..."
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

TARGET_IMAGE="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/staging-app-image:latest"

echo "Building App Image (this might take a minute)..."
docker build -t staging-app-image:latest -f ../../../../Dockerfile ../../../../

echo "Tagging for ECR..."
docker tag staging-app-image:latest "${TARGET_IMAGE}"

echo "Pushing to ECR..."
docker push "${TARGET_IMAGE}"

echo "App Image pushed successfully!"
