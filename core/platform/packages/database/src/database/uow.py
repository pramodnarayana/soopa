from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from database.interceptors import intercept_db_errors


class BaseSqlAlchemyUnitOfWork:
    """
    Centralized Base Unit of Work for all domains.
    Handles transaction lifecycle and common error translation (e.g. IntegrityError).
    """

    session: AsyncSession

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def __aenter__(self) -> Self:
        if not self.session.in_transaction():
            await self.session.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        try:
            await self._pre_commit()
            async with intercept_db_errors():
                await self.session.flush()
                await self.session.commit()
        except Exception:
            await self.rollback()
            raise

        await self._post_commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def _pre_commit(self) -> None:
        """Hook method called immediately before flushing and committing."""

    async def _post_commit(self) -> None:
        """Hook method called immediately after successful commit."""
