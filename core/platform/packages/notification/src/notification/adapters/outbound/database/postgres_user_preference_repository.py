import structlog
from database.models.notifications import (
    UserNotificationPreference as ORMUserNotificationPreference,
)
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ....domain.models import Channel, UserNotificationPreference
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
        return self._to_domain(orm_pref)

    async def get_user_preferences(
        self, tenant_id: str, user_id: str
    ) -> list[UserNotificationPreference]:
        stmt = select(ORMUserNotificationPreference).where(
            ORMUserNotificationPreference.tenant_id == tenant_id,
            ORMUserNotificationPreference.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return [self._to_domain(orm_pref) for orm_pref in result.scalars().all()]

    async def save_preference(self, preference: UserNotificationPreference) -> None:
        stmt = (
            insert(ORMUserNotificationPreference)
            .values(
                id=preference.id,
                tenant_id=preference.tenant_id,
                user_id=preference.user_id,
                event_type=preference.event_type,
                channel=preference.channel.value,
                is_enabled=preference.is_enabled,
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "user_id", "event_type", "channel"],
                set_={"is_enabled": preference.is_enabled},
            )
        )
        await self.session.execute(stmt)

    def _to_domain(self, orm_pref: ORMUserNotificationPreference) -> UserNotificationPreference:
        return UserNotificationPreference(
            id=orm_pref.id,
            tenant_id=orm_pref.tenant_id,
            user_id=orm_pref.user_id,
            event_type=orm_pref.event_type,
            channel=Channel(orm_pref.channel),
            is_enabled=orm_pref.is_enabled,
        )
