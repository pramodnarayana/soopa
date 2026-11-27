"""Shared helper for recording atomic `USER_REVOCATION` tombstones into `config_sync.config_changelog`."""

from __future__ import annotations

from config_sync.domain.checksum import compute_payload_checksum
from config_sync.domain.enums import ConfigChangeAction
from database.config_changelog import record_config_changelog_entry
from seedwork.domain.types import JsonDict
from seedwork.utils import generate_id
from sqlalchemy.ext.asyncio import AsyncSession

from identity.domain.constants import (
    IDENTITY_CONFIG_APP_ID,
    IdentityConfigEntityType,
    IdentityIdPrefix,
)


async def record_user_revocation_tombstone(
    session: AsyncSession,
    *,
    tenant_id: str,
    user_id: str,
    action: ConfigChangeAction,
    reason: str,
) -> None:
    """Append an ACID `USER_REVOCATION` tombstone in the caller's transaction for <200ms cache eviction."""
    payload: JsonDict = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "reason": reason,
    }
    await record_config_changelog_entry(
        session,
        event_id=generate_id(IdentityIdPrefix.IDENTITY_OUTBOX.value),
        app_id=IDENTITY_CONFIG_APP_ID,
        tenant_id=tenant_id,
        entity_type=IdentityConfigEntityType.USER_REVOCATION.value,
        entity_id=user_id,
        action=action.value,
        checksum=compute_payload_checksum(payload),
        payload=payload,
    )
