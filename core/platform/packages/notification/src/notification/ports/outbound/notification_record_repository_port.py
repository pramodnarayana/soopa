from typing import Protocol

from notification.domain.models import NotificationDispatch


class NotificationRecordRepositoryPort(Protocol):
    async def save(self, dispatch: NotificationDispatch) -> None: ...
