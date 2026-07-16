from datetime import UTC
from typing import Any
from uuid import UUID

from api.domain.models import ApiTokenListEntity
from api.ports.api_token_repository import ApiTokenRepositoryPort
from database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from database.models.control_plane import (
    ApiToken,
)
from sqlalchemy import delete, or_, select, update


class SqlAlchemyApiTokenRepository(ApiTokenRepositoryPort):
    """Repository for managing platform API tokens in the global (control plane) DB."""

    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)  # type: ignore

    async def create_api_token(
        self,
        tenant_id: int,
        name: str,
        client_id: str,
        secret_hash: str,
        expires_at: object | None = None,
    ) -> UUID:
        import uuid as uuid_module

        token_id = uuid_module.uuid4()
        record = ApiToken(
            id=token_id,
            tenant_id=tenant_id,
            name=name,
            client_id=client_id,
            secret_hash=secret_hash,
            expires_at=expires_at,
            active=False,
        )
        self.session.add(record)  # type: ignore
        await self.session.flush()  # type: ignore
        return token_id

    async def list_api_tokens(self, tenant_id: int) -> list[ApiTokenListEntity]:
        result = await self.session.execute(  # type: ignore
            select(ApiToken)
            .where(ApiToken.tenant_id == tenant_id)
            .order_by(ApiToken.created_at.desc())
        )
        tokens = result.scalars().all()
        return [
            ApiTokenListEntity(
                id=str(t.id),
                name=t.name,
                client_id=t.client_id,  # safe to return; secret_hash is never exposed
                active=t.active,
                last_used_at=t.last_used_at.isoformat() if t.last_used_at else None,
                expires_at=t.expires_at.isoformat() if t.expires_at else None,
                created_at=t.created_at.isoformat(),
            )
            for t in tokens
        ]

    async def get_api_token(self, tenant_id: int, token_id: UUID) -> dict[str, Any] | None:
        result = await self.session.execute(  # type: ignore
            select(ApiToken).where(ApiToken.id == token_id, ApiToken.tenant_id == tenant_id)
        )
        t = result.scalars().first()
        if not t:
            return None
        return {
            "id": str(t.id),
            "name": t.name,
            "client_id": t.client_id,
            "active": t.active,
        }

    async def update_api_token(
        self, tenant_id: int, token_id: UUID, name: str | None = None, active: bool | None = None
    ) -> bool:
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = name
        if active is not None:
            values["active"] = active

        if not values:
            return True

        stmt = (
            update(ApiToken)
            .where(ApiToken.id == token_id, ApiToken.tenant_id == tenant_id)
            .values(**values)
        )
        result = await self.session.execute(stmt)  # type: ignore
        await self.session.flush()  # type: ignore
        return (getattr(result, "rowcount", 0) or 0) > 0

    async def delete_api_token(self, tenant_id: int, token_id: UUID) -> bool:
        result = await self.session.execute(  # type: ignore
            delete(ApiToken).where(ApiToken.id == token_id, ApiToken.tenant_id == tenant_id)
        )
        await self.session.flush()  # type: ignore
        return (getattr(result, "rowcount", 0) or 0) > 0

    async def get_tenant_id_by_credentials(self, client_id: str, secret_hash: str) -> int | None:
        """
        Two-step lookup (indexed client_id → hash check → tenant_id).
        Step 1: Find row by client_id (plaintext index — O(1), no full scan).
        Step 2: Verify secret_hash matches (prevents timing attacks via constant-time compare).
        Also updates last_used_at.
        """
        import hmac
        from datetime import datetime, timedelta

        from sqlalchemy import update

        now = datetime.now(UTC).replace(tzinfo=None)
        result = await self.session.execute(  # type: ignore
            select(ApiToken).where(
                ApiToken.client_id == client_id,
                ApiToken.active.is_(True),
                or_(ApiToken.expires_at.is_(None), ApiToken.expires_at > now),
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            return None

        # Constant-time comparison prevents timing-based secret enumeration
        if not hmac.compare_digest(record.secret_hash, secret_hash):
            return None

        if not record.last_used_at or record.last_used_at < (now - timedelta(hours=1)):
            await self.session.execute(  # type: ignore
                update(ApiToken).where(ApiToken.id == record.id).values(last_used_at=now)
            )
        return record.tenant_id  # type: ignore
