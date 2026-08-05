import hmac
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from platform_orm.models.identity import ApiToken


class IdentityClient:
    """
    Client for interacting with Platform Identity services.
    Provides timing-attack safe authentication lookups for Bounded Contexts.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_tenant_id_by_credentials(self, client_id: str, secret_hash: str) -> str | None:
        """
        Two-step lookup (indexed client_id → hash check → tenant_id).
        Step 1: Find row by client_id (plaintext index — O(1), no full scan).
        Step 2: Verify secret_hash matches (prevents timing attacks via constant-time compare).
        Also updates last_used_at.
        """
        now = datetime.now(UTC)
        result = await self.session.execute(
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
            await self.session.execute(
                update(ApiToken).where(ApiToken.id == record.id).values(last_used_at=now)
            )
        return str(record.tenant_id)
