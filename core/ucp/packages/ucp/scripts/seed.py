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

        # Map the user to the platform tenant
        await conn.execute(
            """
            INSERT INTO identity.tenant_users (tenant_id, user_id, role, active, created_at, updated_at)
            VALUES ($1, $2, 'admin', true, NOW(), NOW())
            ON CONFLICT (tenant_id, user_id) DO UPDATE SET
                role = EXCLUDED.role,
                active = EXCLUDED.active,
                updated_at = NOW()
            """,
            PLATFORM_SENTINEL_ID,
            platform_user_id,
        )
        logger.info("Successfully seeded platform admin user and mapped to tenant.")

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
