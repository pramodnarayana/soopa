import uuid

from database.models.notifications import NotificationTemplate
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ....domain.models import PLATFORM_TENANT_ID, Channel, Template


class SqlAlchemyTemplateRepository:
    """
    PostgreSQL adapter for the Notification Template Aggregate.
    Handles read/dispatch requests as well as CRUD configuration requests.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -----------------------------------------------------------------------
    # TemplateRepositoryPort — dispatch engine read path
    # -----------------------------------------------------------------------

    async def get_template(
        self, tenant_id: str, event_type: str, channel: Channel
    ) -> Template | None:
        """
        Fetches the active template for a (tenant_id, event_type, channel) triplet.
        Falls back to the platform sentinel tenant (ten_000) if no tenant-specific
        template exists, enabling platform-level default template seeding.
        """
        for lookup_tenant in (tenant_id, PLATFORM_TENANT_ID):
            stmt = select(NotificationTemplate).where(
                NotificationTemplate.tenant_id == lookup_tenant,
                NotificationTemplate.event_type == event_type,
                NotificationTemplate.channel == channel.value,
                NotificationTemplate.is_active.is_(True),
            )
            result = await self.session.execute(stmt)
            row = result.scalars().first()
            if row:
                return self._map_template(row)
        return None

    # -----------------------------------------------------------------------
    # NotificationTemplatesRepositoryPort — API layer
    # -----------------------------------------------------------------------

    async def list_templates(self, tenant_id: str) -> list[Template]:
        stmt = select(NotificationTemplate).where(
            NotificationTemplate.tenant_id == tenant_id,
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [self._map_template(row) for row in rows]

    async def upsert_template(
        self,
        tenant_id: str,
        name: str,
        event_type: str,
        channel: str,
        subject_template: str | None,
        body_template: str,
        is_active: bool,
    ) -> Template:
        stmt = (
            insert(NotificationTemplate)
            .values(
                id=f"{NotificationTemplate.ID_PREFIX}_{uuid.uuid4().hex}",
                tenant_id=tenant_id,
                name=name,
                event_type=event_type,
                channel=channel,
                subject_template=subject_template,
                body_template=body_template,
                is_active=is_active,
            )
            .on_conflict_do_update(
                constraint="notification_template_idx",
                set_={
                    "name": name,
                    "subject_template": subject_template,
                    "body_template": body_template,
                    "is_active": is_active,
                },
            )
            .returning(NotificationTemplate)
        )
        result = await self.session.execute(stmt)
        row = result.scalars().one()
        return self._map_template(row)

    async def delete_template(self, tenant_id: str, template_id: str) -> bool:
        stmt = (
            delete(NotificationTemplate)
            .where(
                NotificationTemplate.tenant_id == tenant_id,
                NotificationTemplate.id == template_id,
            )
            .returning(NotificationTemplate.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    @staticmethod
    def _map_template(row: NotificationTemplate) -> Template:
        return Template(
            id=row.id,
            tenant_id=row.tenant_id,
            name=row.name,
            event_type=row.event_type,
            channel=Channel(row.channel),
            subject=row.subject_template,
            body_content=row.body_template,
            is_active=row.is_active,
        )
