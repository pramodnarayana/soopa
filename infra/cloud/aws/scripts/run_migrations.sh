#!/usr/bin/env bash
set -e

# Usage: ./run_migrations.sh [environment]
# Example: ./run_migrations.sh staging

ENV=${1:-staging}

echo "Deploying migrations for environment: $ENV"

# 1. Fetch AWS network configuration and task definition from Pulumi stack outputs
cd "$(dirname "$0")/../apps/migrator"
NETWORK_CONFIG=$(pulumi stack output cli_network_configuration --stack $ENV)
TASK_DEF=$(pulumi stack output task_definition_family --stack $ENV)
CLUSTER="${ENV}-cluster"

# 2. Trigger the migration ECS Task
echo "Triggering ECS Task: $TASK_DEF on cluster $CLUSTER..."
TASK_ARN=$(aws ecs run-task \
  --cluster "$CLUSTER" \
  --task-definition "$TASK_DEF" \
  --launch-type FARGATE \
  --network-configuration "$NETWORK_CONFIG" \
  --query "tasks[0].taskArn" \
  --output text)

echo "Started Migration Task: $TASK_ARN"

# 3. Wait for the task to finish
echo "Waiting for task to complete (this may take a minute)..."
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK_ARN"

# 4. Check the exit code
EXIT_CODE=$(aws ecs describe-tasks \
  --cluster "$CLUSTER" \
  --tasks "$TASK_ARN" \
  --query "tasks[0].containers[0].exitCode" \
  --output text)

if [ "$EXIT_CODE" = "0" ]; then
    echo "✅ Migrations completed successfully!"

    # Let's fetch the last few lines of the logs to show success
    echo "--- Migration Logs ---"
    aws logs tail /ecs/${ENV}-migrator-migrator --format short | tail -n 15
    exit 0
else
    echo "❌ Migrations failed with exit code $EXIT_CODE."
    echo "--- Error Logs ---"
    aws logs tail /ecs/${ENV}-migrator-migrator --format short | tail -n 30
    exit 1
fi
