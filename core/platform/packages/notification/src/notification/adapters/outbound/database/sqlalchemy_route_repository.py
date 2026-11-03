from database.models.notifications import NotificationRouteConfiguration
from seedwork import generate_id
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from notification.domain.constants import NotificationIdPrefix
from notification.domain.enums import Channel
from notification.domain.preference import NotificationPreference


class SqlAlchemyNotificationRouteRepository:
    """
    PostgreSQL adapter for the Notification Routing Aggregate.
    Handles read/dispatch requests as well as CRUD configuration requests.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -----------------------------------------------------------------------
    # NotificationRouteRepositoryPort — dispatch engine read path
    # -----------------------------------------------------------------------

    async def get_channels(self, tenant_id: str, event_type: str) -> list[Channel]:
        """
        Fetches configured delivery channels for a specific event type.
        Returns empty list if no custom routing exists.
        """
        stmt = select(NotificationRouteConfiguration.channels).where(
            NotificationRouteConfiguration.tenant_id == tenant_id,
            NotificationRouteConfiguration.event_type == event_type,
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()

        if not row:
            return []

        return [Channel(c) for c in row]

    # -----------------------------------------------------------------------
    # NotificationPreferencesRepositoryPort — API layer
    # -----------------------------------------------------------------------

    async def list_preferences(self, tenant_id: str) -> list[NotificationPreference]:
        stmt = select(NotificationRouteConfiguration).where(
            NotificationRouteConfiguration.tenant_id == tenant_id,
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [self._to_domain_model(row) for row in rows]

    async def upsert_preference(
        self,
        tenant_id: str,
        event_type: str,
        channels: list[str],
    ) -> NotificationPreference:
        candidate = NotificationPreference(
            id=generate_id(NotificationIdPrefix.NOTIFICATION_ROUTE.value),
            tenant_id=tenant_id,
            event_type=event_type,
            channels=tuple(Channel(c) for c in channels),
        )
        orm_record = self._to_orm_record(candidate)
        stmt = (
            insert(NotificationRouteConfiguration)
            .values(
                id=orm_record.id,
                tenant_id=orm_record.tenant_id,
                event_type=orm_record.event_type,
                channels=orm_record.channels,
            )
            .on_conflict_do_update(
                constraint="notification_route_idx",
                set_={"channels": orm_record.channels},
            )
            .returning(NotificationRouteConfiguration)
        )
        result = await self.session.execute(stmt)
        row = result.scalars().one()
        return self._to_domain_model(row)

    async def delete_preference(self, tenant_id: str, event_type: str) -> bool:
        stmt = (
            delete(NotificationRouteConfiguration)
            .where(
                NotificationRouteConfiguration.tenant_id == tenant_id,
                NotificationRouteConfiguration.event_type == event_type,
            )
            .returning(NotificationRouteConfiguration.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    @staticmethod
    def _to_domain_model(row: NotificationRouteConfiguration) -> NotificationPreference:
        return NotificationPreference(
            id=row.id,
            tenant_id=row.tenant_id,
            event_type=row.event_type,
            channels=tuple(Channel(c) for c in row.channels),
        )

    @staticmethod
    def _to_orm_record(preference: NotificationPreference) -> NotificationRouteConfiguration:
        record_id = (
            preference.id
            if preference.id
            else generate_id(NotificationIdPrefix.NOTIFICATION_ROUTE.value)
        )
        return NotificationRouteConfiguration(
            id=record_id,
            tenant_id=preference.tenant_id,
            event_type=preference.event_type,
            channels=[channel.value for channel in preference.channels],
        )

    @staticmethod
    def _update_record_from_domain(
        row: NotificationRouteConfiguration, preference: NotificationPreference
    ) -> None:
        row.tenant_id = preference.tenant_id
        row.event_type = preference.event_type
        row.channels = [channel.value for channel in preference.channels]
