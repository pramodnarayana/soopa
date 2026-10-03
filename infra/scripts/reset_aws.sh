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
# 1. Wipe Zitadel Organizations via UCP Worker Task
# ---------------------------------------------------------
echo "1. Wiping Zitadel Organizations via ECS Task ($UCP_WORKER_TASK_DEF)..."

ZITADEL_WIPE_SCRIPT=$(cat << 'EOF'
import asyncio, os, sys
from identity_worker.config.settings import AppSettings
from identity_worker.adapters.outbound.identity_provider.zitadel_organizations_adapter import ZitadelOrganizationsAdapter
from identity_worker.adapters.outbound.identity_provider.zitadel_project_provider import ZitadelProjectProvider

async def main():
    print("Initializing Zitadel adapters to wipe test orgs...")
    os.environ["WORKER_MODULES"] = "identity-worker"
    settings = AppSettings()
    project_provider = ZitadelProjectProvider(settings)
    org_provider = ZitadelOrganizationsAdapter(project_provider, settings)

    res = await org_provider.fetch_with_auth("/admin/v1/orgs/_search", method="POST", json={})
    orgs = res.json().get("result", [])

    platform_org_id = settings.zitadel_platform_org_id
    deleted_count = 0
    for org in orgs:
        org_id = org.get("id")
        org_name = org.get("name")
        if org_id == platform_org_id or org_name == "ZITADEL" or org_name == "System":
            print(f"Skipping core org: {org_name} ({org_id})")
            continue

        print(f"Deleting test org: {org_name} ({org_id})")
        try:
            await org_provider.delete_organization(org_id)
            deleted_count += 1
        except Exception as e:
            print(f"Failed to delete {org_id}: {e}")

    print(f"Successfully deleted {deleted_count} organizations from Zitadel.")

asyncio.run(main())
EOF
)

# Convert python script to base64 so we can safely pass it as a command override
ZITADEL_B64=$(echo "$ZITADEL_WIPE_SCRIPT" | base64 | tr -d '\n')

UCP_RUN_OUTPUT=$(aws ecs run-task \
  --cluster "$CLUSTER" \
  --task-definition "$UCP_WORKER_TASK_DEF" \
  --launch-type FARGATE \
  --network-configuration "$NETWORK_CONFIG" \
  --overrides "{\"containerOverrides\": [{\"name\": \"app\", \"command\": [\"sh\", \"-c\", \"echo $ZITADEL_B64 | base64 -d > /tmp/wipe_zitadel.py && python /tmp/wipe_zitadel.py\"]}]}" \
  --query '{taskArn: tasks[0].taskArn}')

UCP_TASK_ARN=$(echo "$UCP_RUN_OUTPUT" | grep -Eo '"taskArn":\s*"[^"]+"' | cut -d'"' -f4 || echo "")
echo "Started Zitadel Wipe Task: $UCP_TASK_ARN"
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$UCP_TASK_ARN"
echo "✅ Zitadel wipe completed!"


# ---------------------------------------------------------
# 2. Wipe Databases via Migrator Task
# ---------------------------------------------------------
echo "2. Wiping Databases via ECS Task ($MIGRATOR_TASK_DEF)..."

DB_WIPE_SCRIPT=$(cat << 'EOF'
import asyncio, os, sys
import asyncpg

async def drop_all_schemas(dsn: str, db_name: str):
    print(f"Dropping all application schemas on {db_name}...")
    try:
        conn = await asyncpg.connect(dsn)
        rows = await conn.fetch("SELECT schema_name FROM information_schema.schemata;")
        schemas = [row["schema_name"] for row in rows]

        schemas_to_drop = [
            s for s in schemas
            if s not in ("information_schema", "zitadel", "eventstore", "projections", "authz", "system", "cache", "logstore") and not s.startswith("pg_")
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
# 3. Re-run Migrations
# ---------------------------------------------------------
echo "3. Re-running database migrations and seeds to restore baseline..."
cd "$SCRIPT_DIR"
./run_migrations.sh $ENV

echo "🎉 AWS Environment $ENV has been fully reset and re-seeded!"
