"""Startup diagnostic check for Platform Sentinel Tenant IdP Organization alignment."""

from __future__ import annotations

import structlog
from database.models.identity import Tenant as TenantORM
from database.provider import DatabaseProvider
from database.utils import DATABASE_CONNECTION_ERRORS
from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import select

logger = structlog.get_logger(__name__)

IDENTITY_DRIFT_REMEDY = "Run 'pnpm db:seed' to sync global_db with .env"


async def verify_platform_tenant_idp_alignment(
    *,
    db_provider: DatabaseProvider,
    expected_platform_org_id: str,
) -> bool:
    """Verify that ``tnt_platform.idp_tenant_id`` matches ``IDENTITY_PLATFORM_ORG_ID``.

    Emits a structured error log with exact remediation steps if the database
    record is missing or holds a stale IdP organization ID, rather than failing
    opaquely on the first authenticated HTTP request.
    """
    normalized_expected = expected_platform_org_id.strip()
    if not normalized_expected:
        return True

    try:
        async with db_provider.session() as session:
            result = await session.execute(
                select(TenantORM.idp_tenant_id).where(TenantORM.id == PLATFORM_TENANT_ID)
            )
            db_org_id = result.scalar_one_or_none()
    except DATABASE_CONNECTION_ERRORS:
        logger.exception(
            "platform_tenant_idp_alignment_check_failed",
            tenant_id=PLATFORM_TENANT_ID,
        )
        return False

    if db_org_id is None:
        logger.error(
            "local_identity_platform_tenant_missing",
            tenant_id=PLATFORM_TENANT_ID,
            env_org_id=normalized_expected,
            remedy=IDENTITY_DRIFT_REMEDY,
        )
        return False

    if db_org_id != normalized_expected:
        logger.error(
            "local_identity_org_id_mismatch",
            tenant_id=PLATFORM_TENANT_ID,
            env_org_id=normalized_expected,
            db_org_id=db_org_id,
            remedy=IDENTITY_DRIFT_REMEDY,
        )
        return False

    return True
