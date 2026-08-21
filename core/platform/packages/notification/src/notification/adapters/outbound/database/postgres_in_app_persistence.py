import json
import uuid
from collections.abc import Callable, Sequence
from typing import Any

import structlog
from platform_orm.models.identity import Role, User, UserRole
from platform_orm.models.notifications import InAppNotification
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ....ports.outbound.in_app_notification_persistence_port import InAppNotificationPersistencePort

logger = structlog.get_logger(__name__)


class SqlAlchemyInAppPersistence(InAppNotificationPersistencePort):
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
                # Fan out to all active users holding an admin-level role in this tenant via PBAC.
                # TenantAdmin is the canonical admin role name.
                stmt = (
                    select(UserRole.user_id)
                    .join(Role, Role.id == UserRole.role_id)
                    .join(User, User.id == UserRole.user_id)
                    .where(
                        UserRole.tenant_id == tenant_id,
                        Role.name.in_(["TenantAdmin", "PlatformAdmin"]),
                        Role.deleted_at.is_(None),
                        User.deleted_at.is_(None),
                        User.status == "active",
                    )
                    .distinct()
                )
                result = await session.execute(stmt)
                user_ids = result.scalars().all()

            if not user_ids:
                logger.warning(
                    "No recipients found for in-app notification: tenant_id=%s, target_user_id=%s, "
                    "event_type=%s. No active admin users with non-deleted roles available.",
                    tenant_id,
                    data.get("target_user_id"),
                    data.get("event_type"),
                )

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

            # Flush to populate ORM-assigned created_at timestamps
            await session.flush()

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
                        "created_at": (notif.created_at.isoformat() if notif.created_at else None),
                    }
                )
                # Escape single quotes in the payload
                safe_payload = payload.replace("'", "''")
                await session.execute(text(f"NOTIFY in_app_notifications, '{safe_payload}'"))
