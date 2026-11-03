from datetime import UTC, datetime
from typing import cast

from database.models.identity import ApiToken as ApiTokenORM
from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from identity.domain.api_token import ApiToken
from identity.ports.outbound.api_token_repository_port import ApiTokenRepositoryPort


class SqlAlchemyApiTokenRepository(ApiTokenRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _to_domain_model(orm_model: ApiTokenORM) -> ApiToken:
        return ApiToken(
            id=orm_model.id,
            tenant_id=orm_model.tenant_id,
            name=orm_model.name,
            client_id=orm_model.client_id,
            secret_hash=orm_model.secret_hash,
            last_used_at=orm_model.last_used_at,
            expires_at=orm_model.expires_at,
            active=orm_model.active,
            created_at=orm_model.created_at,
            updated_at=orm_model.updated_at,
        )

    @staticmethod
    def _to_orm_record(domain_model: ApiToken) -> ApiTokenORM:
        return ApiTokenORM(
            id=domain_model.id,
            tenant_id=domain_model.tenant_id,
            name=domain_model.name,
            client_id=domain_model.client_id,
            secret_hash=domain_model.secret_hash,
            last_used_at=domain_model.last_used_at,
            expires_at=domain_model.expires_at,
            active=domain_model.active,
            created_at=domain_model.created_at,
            updated_at=domain_model.updated_at,
        )

    @staticmethod
    def _update_record_from_domain(orm_model: ApiTokenORM, domain_model: ApiToken) -> None:
        orm_model.name = domain_model.name
        orm_model.last_used_at = domain_model.last_used_at
        orm_model.expires_at = domain_model.expires_at
        orm_model.active = domain_model.active
        orm_model.updated_at = domain_model.updated_at

    async def get_all_by_tenant(self, tenant_id: str) -> list[ApiToken]:
        result = await self.session.execute(
            select(ApiTokenORM)
            .where(ApiTokenORM.tenant_id == tenant_id, ApiTokenORM.deleted_at.is_(None))
            .order_by(ApiTokenORM.created_at.desc())
        )
        return [self._to_domain_model(r) for r in result.scalars().all()]

    async def get_by_id(self, token_id: str, tenant_id: str) -> ApiToken | None:
        result = await self.session.execute(
            select(ApiTokenORM).where(
                ApiTokenORM.id == token_id,
                ApiTokenORM.tenant_id == tenant_id,
                ApiTokenORM.deleted_at.is_(None),
            )
        )
        orm_model = result.scalar_one_or_none()
        return self._to_domain_model(orm_model) if orm_model else None

    async def save(self, token: ApiToken) -> ApiToken:
        result = await self.session.execute(
            select(ApiTokenORM).where(
                ApiTokenORM.id == token.id,
                ApiTokenORM.tenant_id == token.tenant_id,
                ApiTokenORM.deleted_at.is_(None),
            )
        )
        orm_model = result.scalar_one_or_none()
        if orm_model is None:
            orm_model = self._to_orm_record(token)
            self.session.add(orm_model)
        else:
            self._update_record_from_domain(orm_model, token)
        await self.session.flush()
        return self._to_domain_model(orm_model)

    async def delete(self, token_id: str, tenant_id: str) -> bool:
        result = await self.session.execute(
            update(ApiTokenORM)
            .where(
                ApiTokenORM.id == token_id,
                ApiTokenORM.tenant_id == tenant_id,
                ApiTokenORM.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(UTC).replace(tzinfo=None))
        )
        return cast(CursorResult[tuple[()]], result).rowcount > 0

    async def get_by_client_id(self, client_id: str) -> ApiToken | None:
        now = datetime.now(UTC)
        result = await self.session.execute(
            select(ApiTokenORM).where(
                ApiTokenORM.client_id == client_id,
                ApiTokenORM.active.is_(True),
                ApiTokenORM.deleted_at.is_(None),
                or_(ApiTokenORM.expires_at.is_(None), ApiTokenORM.expires_at > now),
            )
        )
        orm_model = result.scalar_one_or_none()
        return self._to_domain_model(orm_model) if orm_model else None
