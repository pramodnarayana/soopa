from typing import Any

from platform_orm.models.identity import ApiToken as ApiTokenORM
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.domain.models.api_token import ApiTokenDomainModel
from ucp.ports.api_token_repository import ApiTokenRepositoryPort


class PostgresApiTokenRepository(ApiTokenRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _to_domain(self, orm_model: ApiTokenORM) -> ApiTokenDomainModel:
        return ApiTokenDomainModel(
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

    def _to_orm(self, domain_model: ApiTokenDomainModel) -> ApiTokenORM:
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

    async def get_all_by_tenant(self, tenant_id: str) -> list[ApiTokenDomainModel]:
        result = await self.session.execute(
            select(ApiTokenORM)
            .where(ApiTokenORM.tenant_id == tenant_id)
            .order_by(ApiTokenORM.created_at.desc())
        )
        return [self._to_domain(r) for r in result.scalars().all()]

    async def get_by_id(self, token_id: str, tenant_id: str) -> ApiTokenDomainModel | None:
        result = await self.session.execute(
            select(ApiTokenORM).where(
                ApiTokenORM.id == token_id, ApiTokenORM.tenant_id == tenant_id
            )
        )
        orm_model = result.scalar_one_or_none()
        return self._to_domain(orm_model) if orm_model else None

    async def create(self, token: ApiTokenDomainModel) -> ApiTokenDomainModel:
        orm_model = self._to_orm(token)
        self.session.add(orm_model)
        await self.session.flush()
        return self._to_domain(orm_model)

    async def update(
        self, token_id: str, tenant_id: str, **kwargs: Any
    ) -> ApiTokenDomainModel | None:
        if not kwargs:
            return await self.get_by_id(token_id, tenant_id)

        result = await self.session.execute(
            update(ApiTokenORM)
            .where(ApiTokenORM.id == token_id, ApiTokenORM.tenant_id == tenant_id)
            .values(**kwargs)
            .returning(ApiTokenORM)
        )
        orm_model = result.scalar_one_or_none()
        return self._to_domain(orm_model) if orm_model else None

    async def delete(self, token_id: str, tenant_id: str) -> bool:
        result = await self.session.execute(
            delete(ApiTokenORM).where(
                ApiTokenORM.id == token_id, ApiTokenORM.tenant_id == tenant_id
            )
        )
        return getattr(result, "rowcount", 0) > 0

    async def get_by_client_id(self, client_id: str) -> ApiTokenDomainModel | None:
        result = await self.session.execute(
            select(ApiTokenORM).where(
                ApiTokenORM.client_id == client_id,
                ApiTokenORM.active,
            )
        )
        orm_model = result.scalar_one_or_none()
        return self._to_domain(orm_model) if orm_model else None
