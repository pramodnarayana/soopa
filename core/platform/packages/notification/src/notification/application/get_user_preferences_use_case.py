import structlog

from ..domain.models import UserNotificationPreference
from ..ports.outbound.uow_port import NotificationUnitOfWorkPort

logger = structlog.get_logger(__name__)


class GetUserPreferencesUseCase:
    def __init__(self, uow: NotificationUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(self, tenant_id: str, user_id: str) -> list[UserNotificationPreference]:
        logger.info("Fetching notification preferences", tenant_id=tenant_id)
        async with self.uow:
            return await self.uow.user_preference_repo.get_user_preferences(tenant_id, user_id)
