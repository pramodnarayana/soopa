#!/usr/bin/env bash
set -e

# Unset LocalStack endpoints if present in the user's environment
unset AWS_ENDPOINT_URL
unset AWS_ENDPOINT_URL_ECS

# Usage: ./dbeaver_tunnel.sh [global|edi]
TARGET_DB=${1:-global}

echo "Starting Secure SSM Tunnel to $TARGET_DB database..."

CLUSTER_ARN=$(aws ecs list-clusters --query 'clusterArns[?contains(@, `staging`)]' --output text)
CLUSTER_NAME=$(basename "$CLUSTER_ARN")

echo "Locating Bastion Host in Cluster: $CLUSTER_NAME..."
SVC_ARN=$(aws ecs list-services --cluster "$CLUSTER_ARN" --query 'serviceArns[?contains(@, `staging-ops-bastion-svc`)]' --output text | awk '{print $1}')
SVC_NAME=$(basename "$SVC_ARN")

TASK_ARN=$(aws ecs list-tasks --cluster "$CLUSTER_ARN" --service-name "$SVC_NAME" --query 'taskArns[0]' --output text)

if [ "$TASK_ARN" = "None" ] || [ -z "$TASK_ARN" ]; then
    echo "❌ Bastion Task is not running. Please deploy 'infra/cloud/aws/apps/ops' first."
    exit 1
fi

TASK_ID=$(basename "$TASK_ARN")

# Get the container Runtime ID (required by SSM for ECS Exec)
RUNTIME_ID=$(aws ecs describe-tasks --cluster "$CLUSTER_ARN" --tasks "$TASK_ARN" \
  --query 'tasks[0].containers[0].runtimeId' --output text)

# Get the DB Endpoint dynamically from Pulumi 'data' stack
cd "$(dirname "$0")/../cloud/aws/data"

if [ "$TARGET_DB" = "edi" ]; then
    DB_HOST=$(pulumi stack output edi_shard_db_endpoint --stack staging)
    LOCAL_PORT=15433
    echo "✅ Port Forwarding Established for EDI Shard! Point DBeaver to localhost:$LOCAL_PORT"
else
    DB_HOST=$(pulumi stack output global_db_endpoint --stack staging)
    LOCAL_PORT=15432
    echo "✅ Port Forwarding Established for Global DB! Point DBeaver to localhost:$LOCAL_PORT"
fi

echo "Press Ctrl+C to close the tunnel."

# Strip the port number (if present) because SSM requires just the hostname
DB_HOST_ONLY=$(echo "$DB_HOST" | cut -d: -f1)

# Start the SSM Session
aws ssm start-session \
    --target "ecs:${CLUSTER_NAME}_${TASK_ID}_${RUNTIME_ID}" \
    --document-name AWS-StartPortForwardingSessionToRemoteHost \
    --parameters "{\"host\":[\"${DB_HOST_ONLY}\"],\"portNumber\":[\"5432\"], \"localPortNumber\":[\"${LOCAL_PORT}\"]}"
