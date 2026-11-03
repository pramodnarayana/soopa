from database.uow import BaseSqlAlchemyUnitOfWork
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from notification.domain.constants import NotificationOutboxChannel
from notification.ports.outbound.notification_outbox_repository_port import (
    NotificationOutboxRepositoryPort,
)
from notification.ports.outbound.notification_record_repository_port import (
    NotificationRecordRepositoryPort,
)
from notification.ports.outbound.notification_route_repository_port import (
    NotificationRouteRepositoryPort,
)
from notification.ports.outbound.template_repository_port import TemplateRepositoryPort
from notification.ports.outbound.uow_port import NotificationUnitOfWorkPort
from notification.ports.outbound.user_notification_preference_repository_port import (
    UserNotificationPreferenceRepositoryPort,
)


class SqlAlchemyNotificationUnitOfWork(BaseSqlAlchemyUnitOfWork, NotificationUnitOfWorkPort):
    """
    Concrete Unit of Work adapter for the Notification context.
    Collaborating repositories are injected as abstract Ports by the Composition Root.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        user_preference_repo: UserNotificationPreferenceRepositoryPort,
        template_repo: TemplateRepositoryPort,
        record_repo: NotificationRecordRepositoryPort,
        route_repo: NotificationRouteRepositoryPort,
        outbox_repo: NotificationOutboxRepositoryPort,
    ) -> None:
        super().__init__(session)
        self.user_preference_repo = user_preference_repo
        self.template_repo = template_repo
        self.record_repo = record_repo
        self.route_repo = route_repo
        self.outbox_repo = outbox_repo

    async def _pre_commit(self) -> None:
        # Wake up the delivery outbox relay
        await self.session.execute(
            text(f"NOTIFY {NotificationOutboxChannel.DELIVERY_WAKEUP.value};")
        )
