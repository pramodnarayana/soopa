from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database.interceptors import intercept_db_errors
from database.replication_watermark import parse_postgres_lsn
from database.types import ReplicationWatermark


class BaseSqlAlchemyUnitOfWork:
    """
    Centralized Base Unit of Work for all domains.

    Handles ACID transaction lifecycle, common error translation, and optional
    causal `ReplicationWatermark` capture for Read-Your-Own-Writes (RYOW).
    """

    session: AsyncSession
    last_commit_watermark: ReplicationWatermark | None

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._owns_transaction: bool = False
        self.last_commit_watermark = None

    async def __aenter__(self) -> Self:
        if not self.session.in_transaction():
            await self.session.begin()
            self._owns_transaction = True
        else:
            self._owns_transaction = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._owns_transaction and self.session.in_transaction():
            await self.rollback()

    async def capture_replication_watermark(self) -> ReplicationWatermark:
        """Sample current PostgreSQL `pg_current_wal_insert_lsn()` post-commit."""
        if self.session.in_transaction():
            raise RuntimeError(
                "Cannot capture replication watermark while a transaction is active; "
                "sampling must occur post-commit on the same writer to include the commit WAL record."
            )
        result = await self.session.execute(text("SELECT pg_current_wal_insert_lsn()::text"))
        lsn_text = str(result.scalar_one())
        watermark = parse_postgres_lsn(lsn_text)
        self.last_commit_watermark = watermark
        return watermark

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


__all__ = ["BaseSqlAlchemyUnitOfWork"]
