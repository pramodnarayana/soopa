"""
Seed Script — Bootstraps the platform Sentinel Tenant into the database.

This runs as part of infra-reset (pnpm infra:phase3-bootstrap) after migrations.
It reads ZITADEL_PLATFORM_ORG_ID from the environment and inserts/upserts
the canonical platform tenant record so the platform admin can log in.
"""

import asyncio
import os
import sys

import asyncpg
import structlog
from dotenv import load_dotenv

load_dotenv()


logger = structlog.get_logger(__name__)

PLATFORM_SENTINEL_ID = "ten_000000000000000000000000"


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        logger.error("DATABASE_URL environment variable is not set.")
        sys.exit(1)

    # asyncpg requires plain postgresql:// (not postgresql+asyncpg://)
    database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    platform_org_id = os.environ.get("ZITADEL_PLATFORM_ORG_ID", "")
    platform_admin_id = os.environ.get("ZITADEL_PLATFORM_ADMIN_ID", "")
    if not platform_admin_id:
        logger.error("ZITADEL_PLATFORM_ADMIN_ID environment variable is not set.")
        sys.exit(1)

    conn = await asyncpg.connect(database_url)
    try:
        logger.info(
            "Seeding platform sentinel tenant (id={PLATFORM_SENTINEL_ID}, org={platform_org_id})...",
            PLATFORM_SENTINEL_ID=PLATFORM_SENTINEL_ID,
            platform_org_id=platform_org_id,
        )

        # Upsert the platform tenant
        await conn.execute(
            """
            INSERT INTO identity.tenants (id, name, slug, idp_tenant_id, status, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'active', NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                slug = EXCLUDED.slug,
                idp_tenant_id = EXCLUDED.idp_tenant_id,
                status = EXCLUDED.status,
                updated_at = NOW()
            """,
            PLATFORM_SENTINEL_ID,
            "Platform Organization",
            "platform",
            platform_org_id,
        )
        logger.info("Successfully seeded platform sentinel tenant.")

        # Check if the platform admin user already exists
        existing_user_id = await conn.fetchval(
            "SELECT id FROM identity.users WHERE idp_user_id = $1",
            platform_admin_id,
        )

        if existing_user_id:
            platform_user_id = existing_user_id
            logger.info(
                "Platform admin user already exists (id={platform_user_id}). Updating...",
                platform_user_id=platform_user_id,
            )
        else:
            platform_user_id = f"usr_{os.urandom(12).hex()}"
            logger.info(
                "Seeding new platform admin user (id={platform_user_id}, idp_user_id={platform_admin_id})...",
                platform_user_id=platform_user_id,
                platform_admin_id=platform_admin_id,
            )

        # Upsert the platform admin user
        await conn.execute(
            """
            INSERT INTO identity.users (id, idp_user_id, email, name, status, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'active', NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET
                idp_user_id = EXCLUDED.idp_user_id,
                email = EXCLUDED.email,
                name = EXCLUDED.name,
                status = EXCLUDED.status,
                updated_at = NOW()
            """,
            platform_user_id,
            platform_admin_id,
            "admin@soopa.io",
            "Platform Admin",
        )

        # Seed Global PBAC Roles
        logger.info("Seeding global standard roles...")

        # We need UUID-based IDs for roles. We can just use static ones or generate them.
        # Using deterministic hashes of the role name so they are idempotent
        import hashlib

        def hash_id(prefix: str, text: str) -> str:
            h = hashlib.sha256(text.encode()).hexdigest()[:16]
            return f"{prefix}_{h}"

        platform_admin_role_id = hash_id("rol", "PlatformAdmin")
        tenant_admin_role_id = hash_id("rol", "TenantAdmin")
        viewer_role_id = hash_id("rol", "Viewer")

        await conn.execute(
            """
            INSERT INTO identity.roles (id, tenant_id, name, description, capabilities, created_at, updated_at)
            VALUES
                ($1, NULL, 'PlatformAdmin', 'Full access to the entire platform.', ARRAY['platform:admin'], NOW(), NOW()),
                ($2, NULL, 'TenantAdmin', 'Full access to manage a specific tenant.', ARRAY['tenant:admin', 'tenant_settings:read', 'tenant_settings:write', 'users:read', 'users:write', 'roles:read', 'roles:write', 'api_keys:read', 'api_keys:write', 'webhooks:read', 'webhooks:write', 'invoices:read', 'invoices:write'], NOW(), NOW()),
                ($3, NULL, 'Viewer', 'Read-only access to a specific tenant.', ARRAY['tenant_settings:read', 'users:read', 'roles:read', 'api_keys:read', 'webhooks:read', 'invoices:read'], NOW(), NOW())
            ON CONFLICT (tenant_id, name) DO UPDATE SET
                description = EXCLUDED.description,
                capabilities = EXCLUDED.capabilities,
                updated_at = NOW()
            """,
            platform_admin_role_id,
            tenant_admin_role_id,
            viewer_role_id,
        )
        logger.info("Successfully seeded global roles.")

        # Map the user to the platform tenant using user_roles
        # Note: Platform Admin role is global (tenant_id=None or tenant_id=PLATFORM_SENTINEL_ID)
        # We assign it scoped to PLATFORM_SENTINEL_ID here for consistency with tenant context
        user_role_id = f"urol_{os.urandom(12).hex()}"
        await conn.execute(
            """
            INSERT INTO identity.user_roles (id, tenant_id, user_id, role_id, created_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (tenant_id, user_id, role_id) DO NOTHING
            """,
            user_role_id,
            PLATFORM_SENTINEL_ID,
            platform_user_id,
            platform_admin_role_id,
        )
        logger.info("Successfully seeded platform admin user and mapped to tenant roles.")

        logger.info("Seeding platform apps...")

        # Upsert the EDI app
        edi_app_id = f"app_{os.urandom(12).hex()}"
        await conn.execute(
            """
            INSERT INTO ucp.apps (id, slug, name, description, created_at, updated_at)
            VALUES ($1, $2, $3, $4, NOW(), NOW())
            ON CONFLICT (slug) DO UPDATE SET
                slug = EXCLUDED.slug,
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                updated_at = NOW()
            """,
            edi_app_id,
            "edi",
            "EDI",
            "B2B Electronic Data Interchange.",
        )
        logger.info("Successfully seeded platform apps.")

        logger.info("Seeding platform core system jobs...")

        existing_job_id = await conn.fetchval(
            "SELECT id FROM scheduling.scheduled_jobs WHERE name = $1 AND app_namespace = $2",
            "NOTIFICATION_OUTBOX_SWEEPER",
            "NOTIFICATION",
        )

        if existing_job_id:
            await conn.execute(
                """
                UPDATE scheduling.scheduled_jobs
                SET target_queue = $1, cron_expression = $2, timezone = $3, max_retries = $4, updated_at = NOW()
                WHERE id = $5
                """,
                "edi-priority-notifications",
                "* * * * *",
                "UTC",
                3,
                existing_job_id,
            )
        else:
            job_id = f"job_{os.urandom(12).hex()}"
            await conn.execute(
                """
                INSERT INTO scheduling.scheduled_jobs
                    (id, name, target_queue, app_namespace, cron_expression, timezone, max_retries, payload, status, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, '{}'::jsonb, 'PENDING', NOW(), NOW())
                """,
                job_id,
                "NOTIFICATION_OUTBOX_SWEEPER",
                "edi-priority-notifications",
                "NOTIFICATION",
                "* * * * *",
                "UTC",
                3,
            )

        logger.info("Successfully seeded platform core system jobs.")

        logger.info("Seeding database shards...")
        await conn.execute(
            """
            INSERT INTO ucp.database_shards (id, name, dsn, status, created_at, updated_at)
            VALUES ($1, $2, $3, 'active', NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                dsn = EXCLUDED.dsn,
                status = EXCLUDED.status,
                updated_at = NOW()
            """,
            "edi_shard_1",
            "EDI Primary Shard",
            "postgresql://edi:edi_password@localhost:5433/edi_shard_1",
        )
        logger.info("Successfully seeded database shards.")

    except Exception:
        logger.exception("Failed to seed platform tenant.")
        sys.exit(1)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
