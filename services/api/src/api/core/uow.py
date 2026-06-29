from typing import Self

from api.adapters.repository import SqlAlchemyControlPlaneRepository, SqlAlchemyDataPlaneRepository
from sqlalchemy.ext.asyncio import AsyncSession


class UnitOfWork:
    """
    Unit of Work (UoW) pattern for the API layer.
    Manages the lifecycle of database transactions across both the global control plane
    and the tenant data plane schemas.
    """

    def __init__(
        self,
        global_session: AsyncSession,
        tenant_session: AsyncSession | None = None,
    ) -> None:
        self.global_session = global_session
        self.tenant_session = tenant_session
        self.control_plane = SqlAlchemyControlPlaneRepository(global_session)
        self.data_plane = SqlAlchemyDataPlaneRepository(tenant_session) if tenant_session else None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        """Commits transactions on both active sessions."""
        await self.global_session.commit()
        if self.tenant_session:
            await self.tenant_session.commit()

    async def rollback(self) -> None:
        """Rolls back transactions on both active sessions."""
        await self.global_session.rollback()
        if self.tenant_session:
            await self.tenant_session.rollback()
