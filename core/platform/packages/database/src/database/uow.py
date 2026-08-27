from types import TracebackType
from typing import Self

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.exceptions import DuplicateEntityError


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
            await self.session.flush()
            await self.session.commit()
            await self._post_commit()
        except IntegrityError as exc:
            # Only convert unique constraint violations to DuplicateEntityError.
            # Re-raise other integrity errors (foreign-key, NOT NULL, check, exclusion).
            pgcode = None
            sqlstate = None
            constraint_name = None

            if hasattr(exc, "orig"):
                # psycopg (asyncpg) exposes pgcode and sqlstate via the orig exception
                pgcode = getattr(exc.orig, "pgcode", None)
                sqlstate = getattr(exc.orig, "sqlstate", None)
                orig_cause = getattr(exc.orig, "__cause__", None)
                if orig_cause is not None:
                    constraint_name = getattr(orig_cause, "constraint_name", None)
                    if not pgcode:
                        pgcode = getattr(orig_cause, "pgcode", None)
                    if not sqlstate:
                        sqlstate = getattr(orig_cause, "sqlstate", None)
                else:
                    constraint_name = getattr(exc.orig, "constraint_name", None)

            # PostgreSQL error code 23505 = unique_violation
            if pgcode == "23505" or sqlstate == "23505":
                raise DuplicateEntityError(
                    message="A unique constraint was violated.",
                    constraint_name=constraint_name,
                ) from exc

            # Re-raise all other IntegrityErrors unchanged
            raise
        except Exception:
            await self.rollback()
            raise

    async def rollback(self) -> None:
        await self.session.rollback()

    async def _pre_commit(self) -> None:
        """Hook method called immediately before flushing and committing."""

    async def _post_commit(self) -> None:
        """Hook method called immediately after successful commit."""
