import structlog
from database.models import Capability as OrmCapability
from database.repository import BaseSqlAlchemyRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from identity.domain.authorization import CapabilityDescriptor
from identity.ports.outbound.capability_repository_port import CapabilityRepositoryPort

logger = structlog.get_logger(__name__)


class SqlAlchemyCapabilityRepository(CapabilityRepositoryPort, BaseSqlAlchemyRepository):
    """
    PostgreSQL adapter for the Enterprise Capability Catalog.
    """

    def __init__(self, session: AsyncSession) -> None:
        BaseSqlAlchemyRepository.__init__(self, session)

    @staticmethod
    def _to_domain_model(row: OrmCapability) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            code=row.code,
            domain=row.domain,
            resource=row.resource,
            action=row.action,
            display_name=row.display_name,
            description=row.description,
            is_sensitive=row.is_sensitive,
        )

    async def list_all(self) -> list[CapabilityDescriptor]:
        bound_logger = logger.bind()
        bound_logger.debug("capability_repo.list_all.started")

        stmt = select(OrmCapability).order_by(
            OrmCapability.domain.asc(),
            OrmCapability.resource.asc(),
            OrmCapability.action.asc(),
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        bound_logger.debug("capability_repo.list_all.completed", count=len(rows))
        return [self._to_domain_model(row) for row in rows]

    async def list_by_domain(self, domain: str) -> list[CapabilityDescriptor]:
        bound_logger = logger.bind(domain=domain)
        bound_logger.debug("capability_repo.list_by_domain.started")

        stmt = (
            select(OrmCapability)
            .where(OrmCapability.domain == domain)
            .order_by(OrmCapability.resource.asc(), OrmCapability.action.asc())
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        bound_logger.debug("capability_repo.list_by_domain.completed", count=len(rows))
        return [self._to_domain_model(row) for row in rows]

    async def get_by_code(self, code: str) -> CapabilityDescriptor | None:
        stmt = select(OrmCapability).where(OrmCapability.code == code)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return self._to_domain_model(row)
