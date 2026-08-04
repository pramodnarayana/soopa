from datetime import UTC

from database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from sqlalchemy import or_, select, update
from ucp_models.identity import (
    ApiToken,
)

from api.ports.api_token_repository import ApiTokenRepositoryPort


class SqlAlchemyApiTokenRepository(ApiTokenRepositoryPort):
    """Repository for managing platform API tokens in the global (control plane) DB."""

    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)  # type: ignore

    async def get_tenant_id_by_credentials(self, client_id: str, secret_hash: str) -> str | None:
        """
        Two-step lookup (indexed client_id → hash check → tenant_id).
        Step 1: Find row by client_id (plaintext index — O(1), no full scan).
        Step 2: Verify secret_hash matches (prevents timing attacks via constant-time compare).
        Also updates last_used_at.
        """
        import hmac
        from datetime import datetime, timedelta

        now = datetime.now(UTC)
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
