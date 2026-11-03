from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from identity.adapters.outbound.database.api_token_repository import SqlAlchemyApiTokenRepository
from identity.adapters.outbound.database.role_repository import SqlAlchemyRoleRepository
from identity.adapters.outbound.database.uow import SqlAlchemyIdentityUnitOfWork
from identity.adapters.outbound.database.user_repository import SqlAlchemyUserRepository


def create_identity_uow(session: AsyncSession) -> SqlAlchemyIdentityUnitOfWork:
    """Composition root factory assembling SqlAlchemyIdentityUnitOfWork with concrete repositories."""
    return SqlAlchemyIdentityUnitOfWork(
        session,
        user_repo=SqlAlchemyUserRepository(session=session),
        role_repo=SqlAlchemyRoleRepository(session=session),
        api_token_repo=SqlAlchemyApiTokenRepository(session=session),
    )


__all__ = ["create_identity_uow"]
