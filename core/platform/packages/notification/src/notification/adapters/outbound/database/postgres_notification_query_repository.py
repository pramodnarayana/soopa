from collections.abc import Callable
from typing import Any

from platform_orm.models.notifications import NotificationRecord
from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from notification.ports.outbound.notification_query_port import (
    NotificationDTO,
    NotificationQueryPort,
)


class SqlAlchemyNotificationQueryRepository(NotificationQueryPort):
    def __init__(self, session_factory: Callable[[], AsyncSession]):
        self.session_factory = session_factory

    async def get_in_app_notifications(
        self, tenant_id: str, user_id: str, limit: int = 50
    ) -> list[NotificationDTO]:
        async with self.session_factory() as session:
            stmt = (
                select(NotificationRecord)
                .where(
                    NotificationRecord.tenant_id == tenant_id,
                    NotificationRecord.user_id == user_id,
                )
                .order_by(NotificationRecord.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            notifications = result.scalars().all()

            return [
                NotificationDTO(
                    id=notif.id,
                    title=notif.title,
                    body=notif.body,
                    severity=notif.severity,
                    is_read=notif.is_read,
                    created_at=notif.created_at.isoformat() if notif.created_at else None,
                )
                for notif in notifications
            ]

    async def mark_as_read(self, tenant_id: str, user_id: str, notification_id: str) -> bool:
        async with self.session_factory() as session, session.begin():
            stmt = (
                update(NotificationRecord)
                .where(
                    NotificationRecord.id == notification_id,
                    NotificationRecord.tenant_id == tenant_id,
                    NotificationRecord.user_id == user_id,
                )
                .values(is_read=True)
            )
            result: CursorResult[Any] = await session.execute(stmt)  # type: ignore[assignment]
            return result.rowcount > 0
