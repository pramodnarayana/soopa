from database.models.notifications import NotificationTemplate
from identity.domain.identity_context import PLATFORM_TENANT_ID
from seedwork import generate_id
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from notification.domain.constants import NotificationIdPrefix
from notification.domain.enums import Channel
from notification.domain.template import Template


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
                return self._to_domain_model(row)
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
        return [self._to_domain_model(row) for row in rows]

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
        candidate = Template(
            id=generate_id(NotificationIdPrefix.NOTIFICATION_TEMPLATE.value),
            tenant_id=tenant_id,
            name=name,
            event_type=event_type,
            channel=Channel(channel),
            subject=subject_template,
            body_content=body_template,
            is_active=is_active,
        )
        orm_record = self._to_orm_record(candidate)
        stmt = (
            insert(NotificationTemplate)
            .values(
                id=orm_record.id,
                tenant_id=orm_record.tenant_id,
                name=orm_record.name,
                event_type=orm_record.event_type,
                channel=orm_record.channel,
                subject_template=orm_record.subject_template,
                body_template=orm_record.body_template,
                is_active=orm_record.is_active,
            )
            .on_conflict_do_update(
                constraint="notification_template_idx",
                set_={
                    "name": orm_record.name,
                    "subject_template": orm_record.subject_template,
                    "body_template": orm_record.body_template,
                    "is_active": orm_record.is_active,
                },
            )
            .returning(NotificationTemplate)
        )
        result = await self.session.execute(stmt)
        row = result.scalars().one()
        return self._to_domain_model(row)

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
    def _to_domain_model(row: NotificationTemplate) -> Template:
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

    @staticmethod
    def _to_orm_record(template: Template) -> NotificationTemplate:
        record_id = (
            template.id
            if template.id
            else generate_id(NotificationIdPrefix.NOTIFICATION_TEMPLATE.value)
        )
        return NotificationTemplate(
            id=record_id,
            tenant_id=template.tenant_id,
            name=template.name,
            event_type=template.event_type,
            channel=template.channel.value,
            subject_template=template.subject,
            body_template=template.body_content,
            is_active=template.is_active,
        )

    @staticmethod
    def _update_record_from_domain(row: NotificationTemplate, template: Template) -> None:
        row.tenant_id = template.tenant_id
        row.name = template.name
        row.event_type = template.event_type
        row.channel = template.channel.value
        row.subject_template = template.subject
        row.body_template = template.body_content
        row.is_active = template.is_active
