"""
Clear Zitadel Script — Deletes all non-platform tenant organisations from Zitadel.

Run as part of infra-reset (pnpm infra:phase1-cleanup) BEFORE tearing down
the main database.

Strategy: Query Zitadel directly for all organisations. Skip the platform
org (identified by ZITADEL_PLATFORM_ORG_ID) and the built-in ZITADEL system
org. Delete everything else. This handles the case where the local DB was
already wiped but Zitadel still has orphaned orgs.

After Zitadel cleanup, truncate the identity.tenants table so the DB is also
clean.

Safety: The Zitadel volume (zitadel_data) is in a SEPARATE docker compose
project (core/ucp/docker-compose-identity.yml) and is NEVER touched by this
script or by pnpm infra:phase2-teardown.
"""

import asyncio
import contextlib
import logging
import os
import sys
from typing import Any

import asyncpg
import httpx
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# The built-in Zitadel system org — never delete this.
ZITADEL_SYSTEM_ORG_NAME = "ZITADEL"


async def list_all_orgs(
    client: httpx.AsyncClient,
    zitadel_url: str,
    api_token: str,
) -> list[dict[str, Any]]:
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }
    response = await client.post(
        f"{zitadel_url}/admin/v1/orgs/_search",
        headers=headers,
        json={"query": {"offset": "0", "limit": 500}},
        timeout=15,
    )
    response.raise_for_status()
    from typing import cast

    return cast(list[dict[str, Any]], response.json().get("result", []))


async def delete_org_from_zitadel(
    client: httpx.AsyncClient,
    zitadel_url: str,
    api_token: str,
    org_id: str,
    org_name: str,
) -> None:
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }
    response = await client.delete(
        f"{zitadel_url}/admin/v1/orgs/{org_id}",
        headers=headers,
        timeout=15,
    )
    if response.status_code == 404:
        logger.warning("Org '%s' (id=%s) not found — skipping.", org_name, org_id)
        return
    if response.status_code >= 400:
        logger.error(
            "Failed to delete org '%s' (id=%s): %s",
            org_name,
            org_id,
            response.text,
        )
        raise RuntimeError(f"Zitadel API error: {response.status_code} {response.text}")

    logger.info("Deleted Zitadel org '%s' (id=%s)", org_name, org_id)


async def main() -> None:
    zitadel_url = os.environ.get("ZITADEL_API_URL", "http://ucp.localhost:8080")
    api_token = os.environ.get("ZITADEL_API_TOKEN", "")
    platform_org_id = os.environ.get("ZITADEL_PLATFORM_ORG_ID", "")

    if not api_token:
        logger.error("ZITADEL_API_TOKEN environment variable is not set.")
        sys.exit(1)
    if not platform_org_id:
        logger.error("ZITADEL_PLATFORM_ORG_ID environment variable is not set.")
        sys.exit(1)

    # --- Step 1: Query Zitadel directly for all orgs ---
    async with httpx.AsyncClient() as http_client:
        all_orgs = await list_all_orgs(http_client, zitadel_url, api_token)

        tenant_orgs = [
            org
            for org in all_orgs
            if org["id"] != platform_org_id and org.get("name") != ZITADEL_SYSTEM_ORG_NAME
        ]

        if not tenant_orgs:
            logger.info("No tenant organisations found in Zitadel. Nothing to delete.")
        else:
            logger.info("Found %d tenant org(s) to delete from Zitadel.", len(tenant_orgs))
            for org in tenant_orgs:
                with contextlib.suppress(RuntimeError):
                    await delete_org_from_zitadel(
                        client=http_client,
                        zitadel_url=zitadel_url,
                        api_token=api_token,
                        org_id=org["id"],
                        org_name=org.get("name", "unknown"),
                    )

    # --- Step 2: Truncate the local tenants table (if the DB is still up) ---
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        logger.warning(
            "DATABASE_URL not set — skipping local identity.tenants truncation. "
            "This is expected if the DB has already been torn down."
        )
        return

    database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    try:
        conn = await asyncpg.connect(database_url)
        try:
            await conn.execute("TRUNCATE identity.tenants CASCADE")
            logger.info("Truncated identity.tenants table.")
        finally:
            await conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Could not truncate identity.tenants: %s (safe to ignore if DB is already down).",
            exc,
        )


if __name__ == "__main__":
    asyncio.run(main())
