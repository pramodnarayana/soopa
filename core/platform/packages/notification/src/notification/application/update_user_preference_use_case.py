import os

import structlog

from ..domain.models import Channel, UserNotificationPreference
from ..ports.outbound.user_notification_preference_repository_port import (
    UserNotificationPreferenceRepositoryPort,
)

logger = structlog.get_logger(__name__)


class UpdateUserPreferenceUseCase:
    def __init__(self, repo: UserNotificationPreferenceRepositoryPort):
        self.repo = repo

    async def execute(
        self, tenant_id: str, user_id: str, event_type: str, channel: str, is_enabled: bool
    ) -> UserNotificationPreference:
        bound_logger = logger.bind(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type=event_type,
            channel=channel,
            is_enabled=is_enabled,
        )
        bound_logger.info("update_user_preference.started")

        pref_id = f"notif_pref_{os.urandom(12).hex()}"

        pref = UserNotificationPreference(
            id=pref_id,
            tenant_id=tenant_id,
            user_id=user_id,
            event_type=event_type,
            channel=Channel(channel),
            is_enabled=is_enabled,
        )

        await self.repo.save_preference(pref)

        # We fetch it back to guarantee we return the single source of truth
        # (especially if the row already existed and the DB performed an UPSERT)
        updated_pref = await self.repo.get_preference(tenant_id, user_id, event_type, channel)
        if not updated_pref:
            bound_logger.error("update_user_preference.verification_failed")
            raise RuntimeError("Failed to read back preference after save.")

        bound_logger.info("update_user_preference.completed", pref_id=updated_pref.id)
        return updated_pref
