"""SQLAlchemy repository adapter for composite `(idp_issuer, idp_subject) -> user_id` links."""

from __future__ import annotations

from datetime import UTC, datetime

from database.models.identity import ExternalIdentity as OrmExternalIdentity
from seedwork.utils import generate_id
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from identity.domain.constants import IdentityIdPrefix
from identity.domain.dtos import ExternalIdentityDTO
from identity.ports.outbound.external_identity_repository_port import (
    ExternalIdentityRepositoryPort,
)


class SqlAlchemyExternalIdentityRepository(ExternalIdentityRepositoryPort):
    """PostgreSQL SQLAlchemy adapter implementing ExternalIdentityRepositoryPort."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_dto(row: OrmExternalIdentity) -> ExternalIdentityDTO:
        return ExternalIdentityDTO(
            id=row.id,
            user_id=row.user_id,
            idp_issuer=row.idp_issuer,
            idp_subject=row.idp_subject,
            idp_realm_name=row.idp_realm_name,
            linked_at=row.linked_at,
        )

    async def find_by_issuer_subject(
        self,
        *,
        idp_issuer: str,
        idp_subject: str,
    ) -> ExternalIdentityDTO | None:
        normalized_issuer = idp_issuer.rstrip("/")
        stmt = select(OrmExternalIdentity).where(
            OrmExternalIdentity.idp_issuer == normalized_issuer,
            OrmExternalIdentity.idp_subject == idp_subject,
        )
        res = await self._session.execute(stmt)
        row = res.scalars().first()
        return self._to_dto(row) if row is not None else None

    async def list_for_user(self, *, user_id: str) -> tuple[ExternalIdentityDTO, ...]:
        stmt = (
            select(OrmExternalIdentity)
            .where(OrmExternalIdentity.user_id == user_id)
            .order_by(OrmExternalIdentity.linked_at.asc())
        )
        res = await self._session.execute(stmt)
        return tuple(self._to_dto(row) for row in res.scalars().all())

    async def link_identity(
        self,
        *,
        user_id: str,
        idp_issuer: str,
        idp_subject: str,
        idp_realm_name: str | None = None,
    ) -> ExternalIdentityDTO:
        normalized_issuer = idp_issuer.rstrip("/")
        new_id = generate_id(IdentityIdPrefix.EXTERNAL_IDENTITY.value)
        now = datetime.now(UTC)

        insert_stmt = (
            pg_insert(OrmExternalIdentity)
            .values(
                id=new_id,
                user_id=user_id,
                idp_issuer=normalized_issuer,
                idp_subject=idp_subject,
                idp_realm_name=idp_realm_name,
                linked_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    OrmExternalIdentity.idp_issuer,
                    OrmExternalIdentity.idp_subject,
                ]
            )
        )
        await self._session.execute(insert_stmt)
        await self._session.flush()

        existing = await self.find_by_issuer_subject(
            idp_issuer=normalized_issuer,
            idp_subject=idp_subject,
        )
        if existing is None:
            return ExternalIdentityDTO(
                id=new_id,
                user_id=user_id,
                idp_issuer=normalized_issuer,
                idp_subject=idp_subject,
                idp_realm_name=idp_realm_name,
                linked_at=now,
            )
        return existing


__all__ = ["SqlAlchemyExternalIdentityRepository"]
