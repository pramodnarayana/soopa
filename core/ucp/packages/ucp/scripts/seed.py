import hashlib

"""
Seed Script — Bootstraps the platform Sentinel Tenant into the database.

This runs as part of infra-reset (pnpm infra:phase3-bootstrap) after migrations.
It reads IDENTITY_PLATFORM_ORG_ID from the environment and inserts/upserts
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
from sqlalchemy import func, or_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from ucp_models.sharding import DatabaseShard
from ucp_models.subscriptions import App

load_dotenv()

logger = structlog.get_logger(__name__)


async def _seed_platform_tenant(conn: AsyncConnection, platform_org_id: str) -> None:
    logger.info(
        "Seeding platform sentinel tenant (id={PLATFORM_TENANT_ID}, org={platform_org_id})...",
        PLATFORM_TENANT_ID=PLATFORM_TENANT_ID,
        platform_org_id=platform_org_id,
    )
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


async def _seed_platform_admin(conn: AsyncConnection, platform_admin_id: str) -> None:
    h = hashlib.sha256(platform_admin_id.encode()).hexdigest()[:16]
    platform_user_id = f"iam_usr_{h}"

    logger.info(
        "Seeding platform admin user (id={platform_user_id}, idp_user_id={platform_admin_id})...",
        platform_user_id=platform_user_id,
        platform_admin_id=platform_admin_id,
    )

    await conn.execute(
        update(User)
        .where(
            func.lower(User.email).in_(["admin@flowwolf.io", "admin@soopa.ai"]),
            or_(User.idp_user_id != platform_admin_id, User.idp_user_id.is_(None)),
        )
        .values(idp_user_id=platform_admin_id)
    )

    stmt_user = (
        pg_insert(User)
        .values(
            id=platform_user_id,
            idp_user_id=platform_admin_id,
            email="admin@flowwolf.io",
            name="Platform Admin",
            status="active",
        )
        .on_conflict_do_update(
            index_elements=[User.idp_user_id],
            set_={
                "email": "admin@flowwolf.io",
                "name": "Platform Admin",
                "status": "active",
            },
        )
        .returning(User.id)
    )
    result = await conn.execute(stmt_user)
    actual_user_id = result.scalar_one()

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


async def _seed_shards(conn: AsyncConnection, shard_db_url: str, ip_shard_db_url: str) -> None:
    if shard_db_url:
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
        logger.info("Successfully seeded EDI primary shard.", shard_id="edi_shard_1")
    else:
        logger.info("Skipping EDI primary shard seeding (no shard DSN provided).")

    if ip_shard_db_url:
        stmt_ip_shard = (
            pg_insert(DatabaseShard)
            .values(
                id="ip_shard_1",
                name="IP Primary Shard",
                dsn=ip_shard_db_url,
                status="active",
            )
            .on_conflict_do_update(
                index_elements=[DatabaseShard.id],
                set_={
                    "name": "IP Primary Shard",
                    "dsn": ip_shard_db_url,
                    "status": "active",
                },
            )
        )
        await conn.execute(stmt_ip_shard)
        logger.info("Successfully seeded IP primary shard.", shard_id="ip_shard_1")
    else:
        logger.info("Skipping IP primary shard seeding (no shard DSN provided).")


async def _seed_edi_app(conn: AsyncConnection, edi_project_id: str) -> None:
    if edi_project_id:
        stmt_app = update(App).where(App.id == "app_edi_core").values(idp_project_id=edi_project_id)
        await conn.execute(stmt_app)
        logger.info("Successfully seeded EDI app IDP project ID.", idp_project_id=edi_project_id)
    else:
        logger.info("Skipping EDI app project ID seeding (no project ID provided).")


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        logger.error("DATABASE_URL environment variable is not set.")
        sys.exit(1)

    database_url = normalize_to_asyncpg(database_url)

    platform_org_id = os.environ.get("IDENTITY_PLATFORM_ORG_ID", "")
    if not platform_org_id:
        logger.error("IDENTITY_PLATFORM_ORG_ID environment variable is not set.")
        sys.exit(1)

    platform_admin_id = os.environ.get("IDENTITY_PLATFORM_ADMIN_ID", "")
    if not platform_admin_id:
        logger.error("IDENTITY_PLATFORM_ADMIN_ID environment variable is not set.")
        sys.exit(1)

    shard_db_url = os.environ.get("DATABASE__SHARD_OVERRIDES__EDI_SHARD_1") or os.environ.get(
        "SHARD_OVERRIDES__EDI_SHARD_1", ""
    )
    if shard_db_url:
        shard_db_url = normalize_to_asyncpg(shard_db_url)

    ip_shard_db_url = (
        os.environ.get("DATABASE__SHARD_OVERRIDES__IP_SHARD_1")
        or os.environ.get("SHARD_OVERRIDES__IP_SHARD_1")
        or os.environ.get("IP_DATABASE_URL", "")
    )
    if ip_shard_db_url:
        ip_shard_db_url = normalize_to_asyncpg(ip_shard_db_url)

    edi_project_id = os.environ.get("IDENTITY_EDI_PROJECT_ID", "")

    engine = create_async_engine(database_url)

    try:
        async with engine.begin() as conn:
            await _seed_platform_tenant(conn, platform_org_id)
            await _seed_platform_admin(conn, platform_admin_id)
            await _seed_shards(conn, shard_db_url, ip_shard_db_url)
            await _seed_edi_app(conn, edi_project_id)
    except Exception:
        logger.exception("Failed to seed platform tenant.")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
