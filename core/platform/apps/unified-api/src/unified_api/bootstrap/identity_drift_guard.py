"""Startup diagnostic check for Platform Sentinel Tenant IdP Organization alignment."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol

import structlog
from database.models.identity import Tenant as TenantORM
from database.utils import DATABASE_CONNECTION_ERRORS
from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

IDENTITY_DRIFT_REMEDY = "Run 'pnpm db:seed' to sync global_db with .env"


class SessionProviderPort(Protocol):
    """Port yielding an async database session context manager."""

    def session(self) -> AbstractAsyncContextManager[AsyncSession]: ...


async def verify_platform_tenant_idp_alignment(
    *,
    db_provider: SessionProviderPort,
    expected_platform_org_id: str,
) -> bool:
    """Verify that ``ten_000000000000000000000000.idp_tenant_id`` matches ``IDENTITY_PLATFORM_ORG_ID``.

    Emits a structured error log with exact remediation steps if the database
    record is missing, lacks an IdP mapping, or holds a stale IdP organization
    ID, rather than failing opaquely on the first authenticated HTTP request.
    """
    normalized_expected = expected_platform_org_id.strip()
    if not normalized_expected:
        return True

    try:
        async with db_provider.session() as session:
            result = await session.execute(
                select(TenantORM.id, TenantORM.idp_tenant_id).where(
                    TenantORM.id == PLATFORM_TENANT_ID,
                    TenantORM.deleted_at.is_(None),
                )
            )
            row = result.one_or_none()
    except DATABASE_CONNECTION_ERRORS:
        logger.exception(
            "platform_tenant_idp_alignment_check_failed",
            tenant_id=PLATFORM_TENANT_ID,
        )
        return False

    if row is None:
        logger.error(
            "local_identity_platform_tenant_missing",
            tenant_id=PLATFORM_TENANT_ID,
            env_org_id=normalized_expected,
            remedy=IDENTITY_DRIFT_REMEDY,
        )
        return False

    db_org_id: str | None = row[1]
    if not db_org_id:
        logger.error(
            "local_identity_platform_org_unset",
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
