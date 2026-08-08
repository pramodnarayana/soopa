from typing import Any

from platform_orm.models.identity import ApiToken
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.ports.api_token_repository import ApiTokenRepositoryPort


class PostgresApiTokenRepository(ApiTokenRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_all_by_tenant(self, tenant_id: str) -> list[ApiToken]:
        result = await self.session.execute(
            select(ApiToken)
            .where(ApiToken.tenant_id == tenant_id)
            .order_by(ApiToken.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, token_id: str, tenant_id: str) -> ApiToken | None:
        result = await self.session.execute(
            select(ApiToken).where(ApiToken.id == token_id, ApiToken.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def create(self, token: ApiToken) -> ApiToken:
        self.session.add(token)
        await self.session.flush()
        return token

    async def update(self, token_id: str, tenant_id: str, **kwargs: Any) -> ApiToken | None:
        if not kwargs:
            return await self.get_by_id(token_id, tenant_id)

        result = await self.session.execute(
            update(ApiToken)
            .where(ApiToken.id == token_id, ApiToken.tenant_id == tenant_id)
            .values(**kwargs)
            .returning(ApiToken)
        )
        return result.scalar_one_or_none()

    async def delete(self, token_id: str, tenant_id: str) -> bool:
        result = await self.session.execute(
            delete(ApiToken).where(ApiToken.id == token_id, ApiToken.tenant_id == tenant_id)
        )
        return getattr(result, "rowcount", 0) > 0

    async def get_by_client_id(self, client_id: str) -> ApiToken | None:
        result = await self.session.execute(
            select(ApiToken).where(
                ApiToken.client_id == client_id,
                ApiToken.active,
            )
        )
        return result.scalar_one_or_none()
