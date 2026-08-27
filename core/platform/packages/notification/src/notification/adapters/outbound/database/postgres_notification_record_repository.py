import json
import uuid
from collections.abc import Sequence

import structlog
from database.models.identity import Role, User, UserRole
from database.models.notifications import NotificationOutbox, NotificationRecord
from database.outbox_serializer import serialize_domain_event
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from notification.domain.models import Channel, NotificationDispatch

from ....ports.outbound.notification_record_repository_port import NotificationRecordRepositoryPort

logger = structlog.get_logger(__name__)


class SqlAlchemyNotificationRecordRepository(NotificationRecordRepositoryPort):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, dispatch: NotificationDispatch) -> None:
        if dispatch.channel == Channel.IN_APP:
            target_user_id = dispatch.target_user_id
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
                        UserRole.tenant_id == dispatch.tenant_id,
                        Role.name.in_(["TenantAdmin", "PlatformAdmin"]),
                        Role.deleted_at.is_(None),
                        User.deleted_at.is_(None),
                        User.status == "active",
                    )
                    .distinct()
                )
                result = await self.session.execute(stmt)
                user_ids = result.scalars().all()

                if not user_ids:
                    logger.warning(
                        "No recipients found for in-app notification: tenant_id=%s, target_user_id=%s, "
                        "event_type=%s. No active admin users with non-deleted roles available.",
                        dispatch.tenant_id,
                        dispatch.target_user_id,
                        dispatch.data.get("event_type"),
                    )

            notifications = []
            for uid in user_ids:
                notification = NotificationRecord(
                    id=f"notif_inapp_{uuid.uuid4().hex}",
                    tenant_id=dispatch.tenant_id,
                    user_id=uid,
                    title=dispatch.subject or "New Notification",
                    body=dispatch.body,
                    is_read=False,
                )
                notifications.append(notification)
                self.session.add(notification)

            # Flush to populate ORM-assigned created_at timestamps
            await self.session.flush()

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
                await self.session.execute(text(f"NOTIFY in_app_notifications, '{safe_payload}'"))

        # Serialize domain events to outbox!
        for event in dispatch.domain_events:
            outbox_orm = NotificationOutbox(
                id=f"notif_ob_{uuid.uuid4().hex}",
                tenant_id=dispatch.tenant_id,
                event_type=event.event_name,
                idempotency_key=getattr(event, "idempotency_key", str(uuid.uuid4())),
                payload=serialize_domain_event(event),
            )
            self.session.add(outbox_orm)
        dispatch.clear_domain_events()
