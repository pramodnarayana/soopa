import structlog
from database.models.notifications import (
    UserNotificationPreference as ORMUserNotificationPreference,
)
from seedwork import generate_id
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from notification.domain.constants import NotificationIdPrefix
from notification.domain.enums import Channel
from notification.domain.preference import UserNotificationPreference

from ....ports.outbound.user_notification_preference_repository_port import (
    UserNotificationPreferenceRepositoryPort,
)

logger = structlog.get_logger(__name__)


class SqlAlchemyUserNotificationPreferenceRepository(UserNotificationPreferenceRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_preference(
        self, tenant_id: str, user_id: str, event_type: str, channel: str
    ) -> UserNotificationPreference | None:
        stmt = select(ORMUserNotificationPreference).where(
            ORMUserNotificationPreference.tenant_id == tenant_id,
            ORMUserNotificationPreference.user_id == user_id,
            ORMUserNotificationPreference.event_type == event_type,
            ORMUserNotificationPreference.channel == channel,
        )
        result = await self.session.execute(stmt)
        orm_pref = result.scalars().first()
        if not orm_pref:
            return None
        return self._to_domain_model(orm_pref)

    async def get_user_preferences(
        self, tenant_id: str, user_id: str
    ) -> list[UserNotificationPreference]:
        stmt = select(ORMUserNotificationPreference).where(
            ORMUserNotificationPreference.tenant_id == tenant_id,
            ORMUserNotificationPreference.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return [self._to_domain_model(orm_pref) for orm_pref in result.scalars().all()]

    async def save_preference(self, preference: UserNotificationPreference) -> None:
        orm_record = self._to_orm_record(preference)
        stmt = (
            insert(ORMUserNotificationPreference)
            .values(
                id=orm_record.id,
                tenant_id=orm_record.tenant_id,
                user_id=orm_record.user_id,
                event_type=orm_record.event_type,
                channel=orm_record.channel,
                is_enabled=orm_record.is_enabled,
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "user_id", "event_type", "channel"],
                set_={"is_enabled": orm_record.is_enabled},
            )
        )
        await self.session.execute(stmt)

    @staticmethod
    def _to_domain_model(orm_pref: ORMUserNotificationPreference) -> UserNotificationPreference:
        return UserNotificationPreference(
            id=orm_pref.id,
            tenant_id=orm_pref.tenant_id,
            user_id=orm_pref.user_id,
            event_type=orm_pref.event_type,
            channel=Channel(orm_pref.channel),
            is_enabled=orm_pref.is_enabled,
        )

    @staticmethod
    def _to_orm_record(preference: UserNotificationPreference) -> ORMUserNotificationPreference:
        record_id = (
            preference.id
            if preference.id
            else generate_id(NotificationIdPrefix.NOTIFICATION_PREFERENCE.value)
        )
        return ORMUserNotificationPreference(
            id=record_id,
            tenant_id=preference.tenant_id,
            user_id=preference.user_id,
            event_type=preference.event_type,
            channel=preference.channel.value,
            is_enabled=preference.is_enabled,
        )

    @staticmethod
    def _update_record_from_domain(
        orm_pref: ORMUserNotificationPreference, preference: UserNotificationPreference
    ) -> None:
        orm_pref.tenant_id = preference.tenant_id
        orm_pref.user_id = preference.user_id
        orm_pref.event_type = preference.event_type
        orm_pref.channel = preference.channel.value
        orm_pref.is_enabled = preference.is_enabled
