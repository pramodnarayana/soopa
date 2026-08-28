from types import TracebackType
from typing import Protocol, Self

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
from notification.ports.outbound.user_notification_preference_repository_port import (
    UserNotificationPreferenceRepositoryPort,
)


class NotificationUnitOfWorkPort(Protocol):
    """
    Port defining the Unit of Work for the Notification bounded context.
    Encapsulates transaction boundaries and provides access to notification repositories.
    """

    user_preference_repo: UserNotificationPreferenceRepositoryPort
    template_repo: TemplateRepositoryPort
    record_repo: NotificationRecordRepositoryPort
    route_repo: NotificationRouteRepositoryPort
    outbox_repo: NotificationOutboxRepositoryPort

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
