#!/usr/bin/env python3
import asyncio
import os
import sys

import asyncpg
import structlog
from dotenv import load_dotenv

# Load root .env
load_dotenv()

from identity_worker.adapters.outbound.identity_provider.zitadel_organizations_adapter import (
    ZitadelOrganizationsAdapter,
)
from identity_worker.adapters.outbound.identity_provider.zitadel_project_provider import (
    ZitadelProjectProvider,
)
from identity_worker.config.settings import AppSettings

logger = structlog.get_logger()


async def wipe_zitadel_orgs(settings: AppSettings):
    """
    Connects to Zitadel via the Organizations Adapter and attempts
    to delete all tenant orgs generated during local/staging tests.
    """
    logger.info("Initializing Zitadel adapters to wipe test orgs...")
    try:
        project_provider = ZitadelProjectProvider(settings)
        org_provider = ZitadelOrganizationsAdapter(project_provider, settings)

        # Admin API search to find all orgs
        res = await org_provider.fetch_with_auth("/admin/v1/orgs/_search", method="POST", json={})
        data = res.json()
        orgs = data.get("result", [])

        # Usually the platform org is the first one or named specifically.
        # We delete all orgs except the platform org (which holds the machine key).
        platform_org_id = settings.zitadel_platform_org_id

        deleted_count = 0
        for org in orgs:
            org_id = org.get("id")
            org_name = org.get("name")
            if org_id == platform_org_id:
                logger.info("Skipping platform org", org_id=org_id, org_name=org_name)
                continue

            logger.info("Deleting test org", org_id=org_id, org_name=org_name)
            try:
                await org_provider.delete_organization(org_id)
                deleted_count += 1
            except Exception as e:  # noqa: BLE001 - Best-effort cleanup script must continue if individual org deletion fails
                logger.warning(
                    "Failed to delete org", org_id=org_id, org_name=org_name, error=str(e)
                )

        logger.info("Successfully deleted %s test organizations from Zitadel.", deleted_count)
    except Exception as e:
        logger.exception(
            "Failed to connect or fetch orgs from Zitadel. Skipping Zitadel wipe.", error=str(e)
        )


async def drop_public_schema(dsn: str, db_name: str):
    logger.info("Dropping 'public' schema", db_name=db_name)
    try:
        conn = await asyncpg.connect(dsn)

        # Drop replication slots first to prevent WAL from filling up the disk
        try:
            slots = await conn.fetch("SELECT slot_name FROM pg_replication_slots")
            for slot in slots:
                logger.info("Dropping replication slot", slot_name=slot["slot_name"])
                await conn.execute(f"SELECT pg_drop_replication_slot('{slot['slot_name']}');")
        except Exception as e:  # noqa: BLE001 - Best-effort cleanup must continue even if replication slot cannot be dropped
            logger.warning("Failed to drop replication slots", error=str(e))

        await conn.execute("DROP SCHEMA IF EXISTS public CASCADE;")
        await conn.execute("CREATE SCHEMA public;")
        await conn.execute("GRANT ALL ON SCHEMA public TO public;")
        await conn.close()
        logger.info("Reset 'public' schema", db_name=db_name)
    except (asyncpg.Error, OSError) as e:
        logger.exception("Failed to reset database", db_name=db_name, error=str(e))
        sys.exit(1)


async def main():
    logger.info("Starting infra:reset...")

    # 1. Wipe Zitadel Orgs
    # We must do this BEFORE dropping the DB schemas in case we wanted to map them,
    # but querying Zitadel directly is safer anyway.
    os.environ["WORKER_MODULES"] = "identity-worker"
    settings = AppSettings()
    await wipe_zitadel_orgs(settings)

    # 2. Wipe Database Schemas
    global_url = os.getenv("DATABASE_URL")
    if not global_url:
        logger.error("DATABASE_URL is not set.")
        sys.exit(1)

    # Note: For local dev, EDI shard uses 5433. In staging it might be different.
    edi_dsn = os.getenv(
        "EDI_DATABASE_URL", "postgresql://edi:edi_password@localhost:5433/edi_shard"
    )

    await drop_public_schema(global_url, "Global DB")
    await drop_public_schema(edi_dsn, "EDI Shard 1")

    logger.info("Infra reset complete! Ready for db:migrate!")


if __name__ == "__main__":
    asyncio.run(main())
