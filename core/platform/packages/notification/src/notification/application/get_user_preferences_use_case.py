import structlog

from ..domain.models import UserNotificationPreference
from ..ports.user_notification_preference_repository_port import (
    UserNotificationPreferenceRepositoryPort,
)

logger = structlog.get_logger(__name__)


class GetUserPreferencesUseCase:
    def __init__(self, repository: UserNotificationPreferenceRepositoryPort) -> None:
        self.repository = repository

    async def execute(self, tenant_id: str, user_id: str) -> list[UserNotificationPreference]:
        logger.info("Fetching notification preferences", tenant_id=tenant_id, user_id=user_id)
        return await self.repository.get_user_preferences(tenant_id, user_id)
