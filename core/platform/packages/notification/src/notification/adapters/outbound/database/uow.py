from database.uow import BaseSqlAlchemyUnitOfWork
from sqlalchemy.ext.asyncio import AsyncSession

from notification.adapters.outbound.database.postgres_notification_record_repository import (
    SqlAlchemyNotificationRecordRepository,
)
from notification.adapters.outbound.database.postgres_outbox_repository import (
    SqlAlchemyNotificationOutboxPublisher,
)
from notification.adapters.outbound.database.postgres_route_repository import (
    SqlAlchemyNotificationRouteRepository,
)
from notification.adapters.outbound.database.postgres_template_repository import (
    SqlAlchemyTemplateRepository,
)
from notification.adapters.outbound.database.postgres_user_preference_repository import (
    SqlAlchemyUserNotificationPreferenceRepository,
)
from notification.ports.outbound.uow_port import NotificationUnitOfWorkPort


class SqlAlchemyNotificationUnitOfWork(BaseSqlAlchemyUnitOfWork, NotificationUnitOfWorkPort):
    """
    Concrete Unit of Work adapter for the Notification context.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.user_preference_repo = SqlAlchemyUserNotificationPreferenceRepository(
            session=self.session
        )
        self.template_repo = SqlAlchemyTemplateRepository(session=self.session)
        self.record_repo = SqlAlchemyNotificationRecordRepository(session=self.session)
        self.route_repo = SqlAlchemyNotificationRouteRepository(session=self.session)
        self.outbox_repo = SqlAlchemyNotificationOutboxPublisher(session=self.session)

    async def _pre_commit(self) -> None:
        from sqlalchemy import text

        # Wake up the delivery outbox relay
        await self.session.execute(text("NOTIFY notification_delivery_outbox_wakeup;"))
