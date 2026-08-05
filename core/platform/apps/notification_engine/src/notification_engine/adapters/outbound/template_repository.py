from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.notifications import NotificationTemplate as DbTemplate

from ...domain.models import Channel, Template


class SqlAlchemyTemplateRepository:
    def __init__(self, session_factory: Callable[[], AsyncSession]):
        self.session_factory = session_factory

    async def get_template(
        self, tenant_id: str, event_type: str, channel: Channel
    ) -> Template | None:
        async with self.session_factory() as session:
            stmt = select(DbTemplate).where(
                DbTemplate.tenant_id == tenant_id,
                DbTemplate.event_type == event_type,
                DbTemplate.channel == channel.value,
                DbTemplate.is_active == True,
            )
            result = await session.execute(stmt)
            db_template = result.scalars().first()

            if db_template:
                return Template(
                    id=db_template.id,
                    tenant_id=db_template.tenant_id,
                    event_type=db_template.event_type,
                    channel=Channel(db_template.channel),
                    subject=db_template.subject_template,
                    body_content=db_template.body_template,
                )
            return None
