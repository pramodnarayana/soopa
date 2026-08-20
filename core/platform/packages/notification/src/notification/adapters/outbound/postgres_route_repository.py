import uuid
from collections.abc import Callable

from platform_orm.models.notifications import NotificationRouteConfiguration
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.models import Channel, NotificationPreference


class SqlAlchemyNotificationRouteRepository:
    """
    PostgreSQL adapter for the Notification Routing Aggregate.
    Handles read/dispatch requests as well as CRUD configuration requests.
    """

    def __init__(self, session_factory: Callable[[], AsyncSession]):
        self._session_factory = session_factory

    # -----------------------------------------------------------------------
    # NotificationRouteRepositoryPort — dispatch engine read path
    # -----------------------------------------------------------------------

    async def get_channels(self, tenant_id: str, event_type: str) -> list[Channel]:
        """
        Fetches configured delivery channels for a specific event type.
        Returns empty list if no custom routing exists.
        """
        async with self._session_factory() as session:
            stmt = select(NotificationRouteConfiguration.channels).where(
                NotificationRouteConfiguration.tenant_id == tenant_id,
                NotificationRouteConfiguration.event_type == event_type,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

        if not row:
            return []

        return [Channel(c) for c in row]

    # -----------------------------------------------------------------------
    # NotificationPreferencesRepositoryPort — API layer
    # -----------------------------------------------------------------------

    async def list_preferences(self, tenant_id: str) -> list[NotificationPreference]:
        async with self._session_factory() as session:
            stmt = select(NotificationRouteConfiguration).where(
                NotificationRouteConfiguration.tenant_id == tenant_id,
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
        return [self._map_preference(row) for row in rows]

    async def upsert_preference(
        self,
        tenant_id: str,
        event_type: str,
        channels: list[str],
    ) -> NotificationPreference:
        async with self._session_factory() as session, session.begin():
            stmt = (
                insert(NotificationRouteConfiguration)
                .values(
                    id=f"notif_rte_{uuid.uuid4().hex}",
                    tenant_id=tenant_id,
                    event_type=event_type,
                    channels=channels,
                )
                .on_conflict_do_update(
                    constraint="notification_route_idx",
                    set_={"channels": channels},
                )
                .returning(NotificationRouteConfiguration)
            )
            result = await session.execute(stmt)
            row = result.scalars().one()
            preference = self._map_preference(row)
        return preference

    async def delete_preference(self, tenant_id: str, event_type: str) -> bool:
        async with self._session_factory() as session, session.begin():
            stmt = (
                delete(NotificationRouteConfiguration)
                .where(
                    NotificationRouteConfiguration.tenant_id == tenant_id,
                    NotificationRouteConfiguration.event_type == event_type,
                )
                .returning(NotificationRouteConfiguration.id)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

    @staticmethod
    def _map_preference(row: NotificationRouteConfiguration) -> NotificationPreference:
        return NotificationPreference(
            id=row.id,
            tenant_id=row.tenant_id,
            event_type=row.event_type,
            channels=[Channel(c) for c in row.channels],
        )
