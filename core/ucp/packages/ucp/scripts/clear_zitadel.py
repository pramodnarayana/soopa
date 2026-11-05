"""Pre-Reset Zitadel Alignment Guard & Non-Platform Organization Cleanup.

Verifies that .env identity coordinates (machine key, platform org ID, platform admin ID,
and UCP project ID) match live Zitadel BEFORE allowing a database reset to proceed, then
deletes non-platform tenant organizations in Zitadel and purges non-platform tenant rows
in bounded chunks without ever truncating the platform sentinel tenant or its roles.
"""

from __future__ import annotations

import asyncio
import os
import sys

import httpx
import structlog
from database.interceptors import PostgresErrorCodes, extract_postgres_error_metadata
from database.provider import DatabaseProvider
from identity.adapters.outbound.zitadel import ZitadelMachineTokenProvider
from seedwork.infra.config import load_repo_env
from shttp import HttpClient
from sqlalchemy.exc import DBAPIError

from ucp.bootstrap.identity_bootstrap import (
    ZitadelIdentityConfig,
    cleanup_non_platform_zitadel_orgs,
    purge_non_platform_tenants,
    verify_zitadel_platform_alignment,
)

load_repo_env(override=False)

logger = structlog.get_logger(__name__)


class _ShttpMachineAccessTokenAdapter:
    """Adapts ZitadelMachineTokenProvider + shttp.HttpClient to AccessTokenProviderPort."""

    def __init__(self, provider: ZitadelMachineTokenProvider, client: HttpClient) -> None:
        self._provider = provider
        self._client = client

    async def get_access_token(self) -> str:
        return await self._provider.get_access_token(self._client)


async def run_clear_zitadel() -> int:
    config = ZitadelIdentityConfig(
        zitadel_url=os.environ.get("IDENTITY_API_URL", "http://ucp.localhost:8080"),
        machine_key=os.environ.get("IDENTITY_MACHINE_KEY", ""),
        platform_org_id=os.environ.get("IDENTITY_PLATFORM_ORG_ID", ""),
        platform_admin_id=os.environ.get("IDENTITY_PLATFORM_ADMIN_ID", ""),
        ucp_project_id=os.environ.get("IDENTITY_UCP_PROJECT_ID", ""),
    )

    async with (
        HttpClient(allow_private_ips=True) as auth_client,
        httpx.AsyncClient() as http_client,
    ):
        token_provider = ZitadelMachineTokenProvider(
            config.zitadel_url,
            config.machine_key,
            allow_private_ips=True,
        )
        alignment = await verify_zitadel_platform_alignment(
            config=config,
            token_provider=_ShttpMachineAccessTokenAdapter(token_provider, auth_client),
            http_client=http_client,
        )
        if not alignment.aligned or alignment.access_token is None:
            logger.error(
                "zitadel_identity_drift_detected_aborting_reset",
                reason=alignment.reason.value if alignment.reason else "unknown",
                detail=alignment.detail,
                remedy=(
                    "Run 'pnpm bootstrap' to re-initialize Zitadel and synchronize .env "
                    "before resetting databases."
                ),
            )
            return 1

        await cleanup_non_platform_zitadel_orgs(
            http_client=http_client,
            zitadel_url=config.zitadel_url,
            access_token=alignment.access_token,
            platform_org_id=config.platform_org_id,
            all_orgs=alignment.all_orgs,
        )

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        return 0

    db_provider = DatabaseProvider.from_url(database_url)
    try:
        await purge_non_platform_tenants(session_factory=db_provider.session)
    except OSError as exc:
        logger.info("local_database_stopped_skipping_tenant_purge", error=str(exc))
    except DBAPIError as exc:
        sqlstate, _ = extract_postgres_error_metadata(exc)
        if sqlstate == PostgresErrorCodes.UNDEFINED_TABLE.value:
            logger.info("local_database_unmigrated_skipping_tenant_purge")
        else:
            logger.exception("non_platform_tenant_purge_failed")
            return 1
    except Exception:
        logger.exception("non_platform_tenant_purge_failed")
        return 1
    finally:
        await db_provider.close()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run_clear_zitadel()))
