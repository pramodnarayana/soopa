import hashlib

"""
Seed Script — Bootstraps the platform Sentinel Tenant into the database.

This runs as part of infra-reset (pnpm infra:phase3-bootstrap) after migrations.
It reads ZITADEL_PLATFORM_ORG_ID from the environment and inserts/upserts
the canonical platform tenant record so the platform admin can log in.
"""

import asyncio
import os
import sys

import structlog

# Need to import our mapped models to use them
from database.models.identity import Tenant, User, UserRole
from database.utils import normalize_to_asyncpg
from dotenv import load_dotenv
from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import delete, func, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import create_async_engine
from ucp_models.sharding import DatabaseShard
from ucp_models.subscriptions import App

load_dotenv()


logger = structlog.get_logger(__name__)


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        logger.error("DATABASE_URL environment variable is not set.")
        sys.exit(1)

    # SQLAlchemy expects asyncpg connection string
    if database_url:
        database_url = normalize_to_asyncpg(database_url)

    platform_org_id = os.environ.get("ZITADEL_PLATFORM_ORG_ID", "")
    platform_admin_id = os.environ.get("ZITADEL_PLATFORM_ADMIN_ID", "")
    if not platform_admin_id:
        logger.error("ZITADEL_PLATFORM_ADMIN_ID environment variable is not set.")
        sys.exit(1)

    shard_db_url = os.environ.get("SHARD_OVERRIDES__EDI_SHARD_1", "")
    if not shard_db_url:
        logger.error("SHARD_OVERRIDES__EDI_SHARD_1 environment variable is not set.")
        sys.exit(1)

    edi_project_id = os.environ.get("ZITADEL_EDI_PROJECT_ID", "")
    if not edi_project_id:
        logger.error("ZITADEL_EDI_PROJECT_ID environment variable is not set.")
        sys.exit(1)

    engine = create_async_engine(database_url)

    try:
        async with engine.begin() as conn:
            logger.info(
                "Seeding platform sentinel tenant (id={PLATFORM_TENANT_ID}, org={platform_org_id})...",
                PLATFORM_TENANT_ID=PLATFORM_TENANT_ID,
                platform_org_id=platform_org_id,
            )

            # Upsert the platform tenant using SQLAlchemy Core
            stmt_tenant = (
                pg_insert(Tenant)
                .values(
                    id=PLATFORM_TENANT_ID,
                    name="Platform Organization",
                    slug="platform",
                    idp_tenant_id=platform_org_id,
                    status="active",
                )
                .on_conflict_do_update(
                    index_elements=[Tenant.id],
                    set_={
                        "name": "Platform Organization",
                        "slug": "platform",
                        "idp_tenant_id": platform_org_id,
                        "status": "active",
                    },
                )
            )
            await conn.execute(stmt_tenant)
            logger.info("Successfully seeded platform sentinel tenant.")

            # Upsert the platform admin user
            # Deterministic user id based on idp_user_id to prevent duplicates across runs

            h = hashlib.sha256(platform_admin_id.encode()).hexdigest()[:16]
            platform_user_id = f"iam_usr_{h}"

            logger.info(
                "Seeding platform admin user (id={platform_user_id}, idp_user_id={platform_admin_id})...",
                platform_user_id=platform_user_id,
                platform_admin_id=platform_admin_id,
            )

            # Guard against Zitadel re-bootstrap: if the admin email already exists
            # with a different idp_user_id (because Zitadel was reset and issued a new
            # admin ID), the ON CONFLICT (idp_user_id) clause below will not fire and
            # the INSERT will collide on uq_users_email_lower. Delete the stale row first.
            await conn.execute(
                delete(User).where(
                    func.lower(User.email) == "admin@soopa.io",
                    User.idp_user_id != platform_admin_id,
                )
            )

            stmt_user = (
                pg_insert(User)
                .values(
                    id=platform_user_id,
                    idp_user_id=platform_admin_id,
                    email="admin@soopa.io",
                    name="Platform Admin",
                    status="active",
                )
                .on_conflict_do_update(
                    index_elements=[User.idp_user_id],
                    set_={
                        "email": "admin@soopa.io",
                        "name": "Platform Admin",
                        "status": "active",
                    },
                )
                .returning(User.id)
            )
            result = await conn.execute(stmt_user)
            actual_user_id = result.scalar_one()

            # Map the user to the platform tenant using user_roles
            platform_admin_role_id = "rol_97f48b1115b74100"  # matches the one from migration
            user_role_id = f"iam_urol_{h}"

            stmt_user_role = (
                pg_insert(UserRole)
                .values(
                    id=user_role_id,
                    tenant_id=PLATFORM_TENANT_ID,
                    user_id=actual_user_id,
                    role_id=platform_admin_role_id,
                )
                .on_conflict_do_nothing(index_elements=["tenant_id", "user_id", "role_id"])
            )
            await conn.execute(stmt_user_role)
            logger.info("Successfully seeded platform admin user and mapped to tenant roles.")

            # Seed the EDI primary shard using the environment-provided DSN.
            # This belongs here (not in the migration) because the DSN is
            # environment-specific — it differs between local, CI, and production.
            stmt_shard = (
                pg_insert(DatabaseShard)
                .values(
                    id="edi_shard_1",
                    name="EDI Primary Shard",
                    dsn=shard_db_url,
                    status="active",
                )
                .on_conflict_do_update(
                    index_elements=[DatabaseShard.id],
                    set_={
                        "name": "EDI Primary Shard",
                        "dsn": shard_db_url,
                        "status": "active",
                    },
                )
            )
            await conn.execute(stmt_shard)
            logger.info("Successfully seeded EDI primary shard.", shard_dsn=shard_db_url)

            # Update the EDI app with the Zitadel Project ID from the environment
            stmt_app = (
                update(App).where(App.id == "app_edi_core").values(idp_project_id=edi_project_id)
            )
            await conn.execute(stmt_app)
            logger.info(
                "Successfully seeded EDI app IDP project ID.", idp_project_id=edi_project_id
            )

    except Exception:
        logger.exception("Failed to seed platform tenant.")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
