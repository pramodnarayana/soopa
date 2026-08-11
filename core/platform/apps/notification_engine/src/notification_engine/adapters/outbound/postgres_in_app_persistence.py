import json
import uuid
from collections.abc import Callable, Sequence
from typing import Any

from platform_orm.models.identity import TenantUser
from platform_orm.models.notifications import InAppNotification
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .channels.in_app_delivery_strategy import InAppPersistencePort


class PostgresInAppPersistence(InAppPersistencePort):
    def __init__(self, session_factory: Callable[[], AsyncSession]):
        self.session_factory = session_factory

    async def save_notification(
        self, tenant_id: str, content: str, subject: str | None, data: dict[str, Any]
    ) -> None:
        async with self.session_factory() as session, session.begin():
            target_user_id = data.get("target_user_id")
            user_ids: Sequence[str]
            if target_user_id:
                user_ids = [target_user_id]
            else:
                stmt = select(TenantUser.user_id).where(
                    TenantUser.tenant_id == tenant_id,
                    TenantUser.role.in_(["admin", "owner", "Admin", "Owner"]),
                    TenantUser.active.is_(True),
                )
                result = await session.execute(stmt)
                user_ids = result.scalars().all()

            notifications = []
            for uid in user_ids:
                notification = InAppNotification(
                    id=f"notif_inapp_{uuid.uuid4().hex}",
                    tenant_id=tenant_id,
                    user_id=uid,
                    title=subject or "New Notification",
                    body=content,
                    is_read=False,
                )
                notifications.append(notification)
                session.add(notification)

            # Issue NOTIFY for each notification, which will only commit if the transaction commits
            for notif in notifications:
                payload = json.dumps(
                    {
                        "tenant_id": notif.tenant_id,
                        "user_id": notif.user_id,
                        "id": notif.id,
                        "title": notif.title,
                        "body": notif.body,
                        "is_read": notif.is_read,
                        "created_at": None,
                    }
                )
                # Escape single quotes in the payload
                safe_payload = payload.replace("'", "''")
                await session.execute(text(f"NOTIFY in_app_notifications, '{safe_payload}'"))
