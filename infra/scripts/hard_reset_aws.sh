#!/usr/bin/env bash
set -e

# Usage: ./reset_aws.sh [environment]
# Example: ./reset_aws.sh staging

ENV=${1:-staging}

echo "======================================================"
echo "⚠️  WARNING: INITIATING FULL DATA RESET FOR $ENV  ⚠️"
echo "======================================================"
echo "This will DROP ALL DATA in the RDS databases and DELETE"
echo "all test organizations from Zitadel."
echo "Press Ctrl+C to abort, or wait 5 seconds to proceed..."
sleep 5

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Fetching AWS network configuration..."
cd "$SCRIPT_DIR/../cloud/aws/apps/migrator"
NETWORK_CONFIG=$(pulumi stack output cli_network_configuration --stack $ENV)
MIGRATOR_TASK_DEF=$(pulumi stack output task_definition_family --stack $ENV)
CLUSTER="${ENV}-cluster"

cd "../ucp/workers"
UCP_WORKER_TASK_DEF="${ENV}-ucp-workers"


# ---------------------------------------------------------
# ---------------------------------------------------------
# 1. Wipe ALL Databases via Migrator Task (Including Zitadel)
# ---------------------------------------------------------
echo "2. Wiping Databases via ECS Task ($MIGRATOR_TASK_DEF)..."

DB_WIPE_SCRIPT=$(cat << 'EOF'
import asyncio, os, sys
import asyncpg

async def drop_all_schemas(dsn: str, db_name: str):
    print(f"Dropping all application schemas on {db_name}...")
    try:
        conn = await asyncpg.connect(dsn)

        # Drop replication slots first to prevent WAL from filling up the disk
        try:
            slots = await conn.fetch("SELECT slot_name FROM pg_replication_slots")
            for slot in slots:
                print(f"Dropping replication slot '{slot['slot_name']}'...")
                await conn.execute(f"SELECT pg_drop_replication_slot('{slot['slot_name']}');")
        except Exception as e:
            print(f"Warning: Failed to drop replication slots on {db_name}: {e}")

        rows = await conn.fetch("SELECT schema_name FROM information_schema.schemata;")
        schemas = [row["schema_name"] for row in rows]

        schemas_to_drop = [
            s for s in schemas
            if s not in ("information_schema", ) and not s.startswith("pg_")
        ]

        for s in schemas_to_drop:
            print(f"Dropping schema '{s}'...")
            await conn.execute(f"DROP SCHEMA IF EXISTS {s} CASCADE;")
            await conn.execute(f"CREATE SCHEMA {s};")
            await conn.execute(f"GRANT ALL ON SCHEMA {s} TO public;")

        await conn.close()
        print(f"Successfully reset schemas {schemas_to_drop} on {db_name}")
    except Exception as e:
        print(f"Failed to reset {db_name}: {e}")
        sys.exit(1)

async def main():
    global_url = os.getenv("GLOBAL_DATABASE_URL")
    edi_url = os.getenv("EDI_DATABASE_URL")

    if global_url:
        await drop_all_schemas(global_url, "Global DB")
    if edi_url:
        await drop_all_schemas(edi_url, "EDI Shard 1")

asyncio.run(main())
EOF
)

DB_B64=$(echo "$DB_WIPE_SCRIPT" | base64 | tr -d '\n')

MIG_RUN_OUTPUT=$(aws ecs run-task \
  --cluster "$CLUSTER" \
  --task-definition "$MIGRATOR_TASK_DEF" \
  --launch-type FARGATE \
  --network-configuration "$NETWORK_CONFIG" \
  --overrides "{\"containerOverrides\": [{\"name\": \"app\", \"command\": [\"sh\", \"-c\", \"echo $DB_B64 | base64 -d > /tmp/wipe_db.py && python /tmp/wipe_db.py\"]}]}" \
  --query '{taskArn: tasks[0].taskArn}')

MIG_TASK_ARN=$(echo "$MIG_RUN_OUTPUT" | grep -Eo '"taskArn":\s*"[^"]+"' | cut -d'"' -f4 || echo "")
echo "Started DB Wipe Task: $MIG_TASK_ARN"
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$MIG_TASK_ARN"
echo "✅ Database wipe completed!"


# ---------------------------------------------------------
# 2. Restart Zitadel to trigger Setup
# ---------------------------------------------------------
echo "2. Restarting Zitadel ECS service to force setup of core databases..."
ZITADEL_SVC=$(aws ecs list-services --cluster "$CLUSTER" --query "serviceArns[?contains(@, 'zitadel-svc')]" --output text | awk '{print $1}')
if [ -n "$ZITADEL_SVC" ]; then
    aws ecs update-service --cluster "$CLUSTER" --service "$ZITADEL_SVC" --force-new-deployment > /dev/null
    echo "Restarting $ZITADEL_SVC. Please wait ~2 minutes for Zitadel to complete setup."
    # Wait for Zitadel to stabilize
    aws ecs wait services-stable --cluster "$CLUSTER" --services "$ZITADEL_SVC"
    echo "✅ Zitadel restarted and database initialized!"
fi

# ---------------------------------------------------------
# 3. Re-run Migrations
# ---------------------------------------------------------
echo "3. Re-running database migrations and seeds to restore baseline..."
cd "$SCRIPT_DIR"
./run_migrations.sh $ENV

echo "🎉 AWS Environment $ENV has been HARD RESET to a completely clean slate!"
