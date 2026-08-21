from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.subscriptions import App as DbApp

from ucp.domain.models.app import App
from ucp.ports.outbound.app_repository_port import AppRepositoryPort


class PostgresAppRepository(AppRepositoryPort):
    """
    PostgreSQL adapter for the AppRepositoryPort port.
    Fetches available platform applications from the database.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_all(self) -> list[App]:
        stmt = select(DbApp).order_by(DbApp.name)
        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        return [
            App(
                id=row.id,
                slug=row.slug,
                name=row.name,
                description=row.description or "",
            )
            for row in rows
        ]

    async def find_by_id(self, app_id: str) -> App | None:
        stmt = select(DbApp).where(DbApp.id == app_id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()

        if not row:
            return None

        return App(
            id=row.id,
            slug=row.slug,
            name=row.name,
            description=row.description or "",
        )
