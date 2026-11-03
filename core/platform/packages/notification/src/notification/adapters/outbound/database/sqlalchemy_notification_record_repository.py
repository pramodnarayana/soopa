import json
from collections.abc import Sequence

import structlog
from database.models.identity import Role, User, UserRole
from database.models.notifications import NotificationOutbox, NotificationRecord
from database.outbox_serializer import serialize_domain_event
from identity.domain.constants import UserStatus
from seedwork.events import DomainEvent
from seedwork.utils import generate_id
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from notification.domain.constants import NotificationIdPrefix, NotificationOutboxChannel
from notification.domain.dispatch import NotificationDispatch
from notification.domain.enums import Channel

from ....ports.outbound.notification_record_repository_port import NotificationRecordRepositoryPort

logger = structlog.get_logger(__name__)


class SqlAlchemyNotificationRecordRepository(NotificationRecordRepositoryPort):
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _to_orm_record(dispatch: NotificationDispatch, user_id: str) -> NotificationRecord:
        return NotificationRecord(
            id=generate_id(NotificationIdPrefix.NOTIFICATION_RECORD.value),
            tenant_id=dispatch.tenant_id,
            user_id=user_id,
            title=dispatch.subject or "New Notification",
            body=dispatch.body,
            is_read=False,
        )

    @staticmethod
    def _to_outbox_orm_record(
        tenant_id: str,
        event: DomainEvent,
    ) -> NotificationOutbox:
        return NotificationOutbox(
            id=generate_id(NotificationIdPrefix.NOTIFICATION_OUTBOX.value),
            tenant_id=tenant_id,
            event_type=event.event_name,
            idempotency_key=event.idempotency_key,
            payload=serialize_domain_event(event),
        )

    async def save(self, dispatch: NotificationDispatch) -> None:
        events = list(dispatch.domain_events)
        dispatch.clear_domain_events()

        inserted_count = 0
        for event in events:
            outbox_orm = self._to_outbox_orm_record(dispatch.tenant_id, event)
            outbox_stmt = (
                pg_insert(NotificationOutbox)
                .values(
                    id=outbox_orm.id,
                    tenant_id=outbox_orm.tenant_id,
                    event_type=outbox_orm.event_type,
                    idempotency_key=outbox_orm.idempotency_key,
                    payload=outbox_orm.payload,
                )
                .on_conflict_do_nothing(index_elements=["idempotency_key"])
                .returning(NotificationOutbox.id)
            )
            inserted_id = (await self.session.execute(outbox_stmt)).scalar_one_or_none()
            if inserted_id is not None:
                inserted_count += 1

        if events and inserted_count == 0:
            logger.info(
                "notification_dispatch_duplicate_skipped",
                tenant_id=dispatch.tenant_id,
                channel=dispatch.channel.value,
                idempotency_key=dispatch.id,
            )
            return

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
                        User.status == UserStatus.ACTIVE,
                    )
                    .distinct()
                )
                result = await self.session.execute(stmt)
                user_ids = result.scalars().all()

                if not user_ids:
                    logger.info(
                        "in_app_notification_skipped_no_recipients",
                        tenant_id=dispatch.tenant_id,
                        target_user_id=dispatch.target_user_id,
                        event_type=dispatch.data.get("event_type"),
                    )

            notifications = []
            for uid in user_ids:
                notification = self._to_orm_record(dispatch, uid)
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
                await self.session.execute(
                    text("SELECT pg_notify(:channel, :payload)"),
                    {
                        "channel": NotificationOutboxChannel.IN_APP_NOTIFICATIONS.value,
                        "payload": payload,
                    },
                )
