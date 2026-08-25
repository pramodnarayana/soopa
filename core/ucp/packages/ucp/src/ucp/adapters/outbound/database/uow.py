from typing import Any, Self

from identity.adapters.outbound.database.api_token_repository import PostgresApiTokenRepository
from identity.adapters.outbound.database.role_repository import PostgresRoleRepository
from identity.adapters.outbound.database.user_repository import PostgresUserRepository
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.adapters.outbound.database.idempotency_repository import SqlAlchemyIdempotencyRepository
from ucp.adapters.outbound.database.postgres_app_repository import PostgresAppRepository
from ucp.adapters.outbound.database.tenant_repository import TenantRepository
from ucp.adapters.outbound.database.webhook_repository import SqlAlchemyWebhookRepository
from ucp.domain.exceptions import DuplicateEntityError
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort


class SqlAlchemyUcpUnitOfWork(UcpUnitOfWorkPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tenant_repo = TenantRepository(session=self.session)
        self.user_repo = PostgresUserRepository(session=self.session)
        self.api_token_repo = PostgresApiTokenRepository(session=self.session)
        self.app_repo = PostgresAppRepository(session=self.session)
        self.role_repo = PostgresRoleRepository(session=self.session)
        self.webhook_repo = SqlAlchemyWebhookRepository(session=self.session)
        self.idempotency_repo = SqlAlchemyIdempotencyRepository(session=self.session)

    async def __aenter__(self) -> Self:
        if not self.session.in_transaction():
            await self.session.begin()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            await self.rollback()
        # Note: We do NOT auto-commit on success here.
        # True UnitOfWork requires explicit .commit() call in the UseCase.

    async def commit(self) -> None:
        try:
            await self.session.execute(text("NOTIFY ucp_outbox_wakeup;"))
            await self.session.execute(text("NOTIFY identity_outbox_wakeup;"))
            await self.session.commit()
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

    async def rollback(self) -> None:
        await self.session.rollback()
