"""
Clear Zitadel Script — Deletes all non-platform tenant organisations from Zitadel.

Run as part of infra-reset (pnpm infra:phase1-cleanup) BEFORE tearing down
the main database.

Strategy: Query Zitadel directly for all organisations. Skip the platform
org (identified by IDENTITY_PLATFORM_ORG_ID) and the built-in ZITADEL system
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
import os
from typing import TypedDict, cast

import httpx
import structlog
from database.provider import get_async_engine
from dotenv import load_dotenv
from identity.adapters.outbound.zitadel import (
    ZitadelMachineAuthenticationError,
    ZitadelMachineTokenProvider,
)
from sqlalchemy import text

load_dotenv()


logger = structlog.get_logger(__name__)

# The built-in Zitadel system org — never delete this.
IDENTITY_SYSTEM_ORG_NAME = "ZITADEL"


class ZitadelOrgDict(TypedDict, total=False):
    id: str
    name: str


async def list_all_orgs(
    client: httpx.AsyncClient,
    zitadel_url: str,
    access_token: str,
) -> list[ZitadelOrgDict]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    response = await client.post(
        f"{zitadel_url}/admin/v1/orgs/_search",
        headers=headers,
        json={"query": {"offset": "0", "limit": 500}},
        timeout=15,
    )
    response.raise_for_status()

    return cast(list[ZitadelOrgDict], response.json().get("result", []))


async def rename_org_in_zitadel(
    client: httpx.AsyncClient,
    zitadel_url: str,
    access_token: str,
    org_id: str,
    new_name: str,
) -> None:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "x-zitadel-orgid": org_id,
    }
    response = await client.put(
        f"{zitadel_url}/management/v1/orgs/me",
        headers=headers,
        json={"name": new_name},
        timeout=15,
    )
    if response.status_code >= 400:
        logger.warning(
            "failed_to_rename_org",
            org_id=org_id,
            new_name=new_name,
            error=response.text,
        )
        # We don't raise here, we still want to try to delete it
    else:
        logger.info("org_renamed_successfully", org_id=org_id, new_name=new_name)


async def delete_org_from_zitadel(
    client: httpx.AsyncClient,
    zitadel_url: str,
    access_token: str,
    org_id: str,
    org_name: str,
) -> None:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    response = await client.delete(
        f"{zitadel_url}/admin/v1/orgs/{org_id}",
        headers=headers,
        timeout=15,
    )
    if response.status_code == 404:
        logger.warning("org_not_found_skipping", org_name=org_name, org_id=org_id)
        return
    if response.status_code >= 400:
        logger.error(
            "failed_to_delete_org",
            org_name=org_name,
            org_id=org_id,
            error=response.text,
        )
        raise RuntimeError(f"Zitadel API error: {response.status_code} {response.text}")

    logger.info("org_deleted", org_name=org_name, org_id=org_id)


async def main() -> None:
    zitadel_url = os.environ.get("IDENTITY_API_URL", "http://ucp.localhost:8080")
    machine_key = os.environ.get("IDENTITY_MACHINE_KEY", "")
    platform_org_id = os.environ.get("IDENTITY_PLATFORM_ORG_ID", "")

    # --- Step 1: Query Zitadel directly for all orgs (best-effort) ---
    if not machine_key or not platform_org_id:
        logger.warning(
            "identity_credentials_not_set_skipping_org_cleanup",
            has_machine_key=bool(machine_key),
            has_platform_org_id=bool(platform_org_id),
        )
    else:
        try:
            async with httpx.AsyncClient() as http_client:
                token_provider = ZitadelMachineTokenProvider(zitadel_url, machine_key)
                access_token = await token_provider.get_access_token(http_client)
                all_orgs = await list_all_orgs(http_client, zitadel_url, access_token)

                tenant_orgs = [
                    org
                    for org in all_orgs
                    if org.get("id")
                    and org.get("id") != platform_org_id
                    and org.get("name") != IDENTITY_SYSTEM_ORG_NAME
                ]

                if not tenant_orgs:
                    logger.info("no_tenant_orgs_found_in_zitadel")
                else:
                    logger.info("tenant_orgs_found_for_deletion", count=len(tenant_orgs))
                    for org in tenant_orgs:
                        with contextlib.suppress(RuntimeError):
                            org_id = org["id"]
                            org_name = org.get("name", "unknown")
                            # Rename to release the unique name constraint before soft-deleting
                            await rename_org_in_zitadel(
                                client=http_client,
                                zitadel_url=zitadel_url,
                                access_token=access_token,
                                org_id=org_id,
                                new_name=f"DELETED-{org_id}",
                            )
                            await delete_org_from_zitadel(
                                client=http_client,
                                zitadel_url=zitadel_url,
                                access_token=access_token,
                                org_id=org_id,
                                org_name=org_name,
                            )
        except (ZitadelMachineAuthenticationError, httpx.HTTPError, Exception) as exc:  # noqa: BLE001 - Best-effort cleanup during reset when Zitadel service may already be down
            logger.warning(
                "zitadel_auth_or_connection_failed_skipping_org_cleanup",
                error=str(exc),
            )

    # --- Step 2: Truncate the local identity.tenants table (if the DB is still up) ---
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        logger.warning("database_url_not_set_skipping_local_tenants_truncation")

    try:
        engine = get_async_engine(database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SET lock_timeout = '5s'"))
                await conn.execute(text("TRUNCATE identity.tenants CASCADE"))
                logger.info("identity_tenants_table_truncated")
        finally:
            await engine.dispose()
    except Exception as exc:  # noqa: BLE001 - Best-effort DB truncate during reset when database may already be torn down
        logger.warning(
            "could_not_truncate_identity_tenants",
            error=str(exc),
        )


if __name__ == "__main__":
    asyncio.run(main())
