"""
Async SQLAlchemy Repositories for EDI AS2.
All queries automatically enforce tenant isolation via the Hybrid Tenancy context.
"""

from identity.tenant_context import get_tenant_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AS2Payload, TradingPartner


class TradingPartnerRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _tenant_id(self) -> int:
        tenant_id = get_tenant_id()
        if tenant_id is None:
            raise RuntimeError("Database queries require an active tenant context.")
        return tenant_id

    async def find_by_as2_id(self, as2_id: str) -> TradingPartner | None:
        """
        Dynamically resolves a Trading Partner for the current tenant.
        This hot-path lookup enables zero-restart Trading Partner CRUD.
        """
        result = await self.session.execute(
            select(TradingPartner).where(
                TradingPartner.tenant_id == self._tenant_id(),
                TradingPartner.as2_id == as2_id,
                TradingPartner.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_public_certificate(self, as2_id: str) -> bytes | None:
        partner = await self.find_by_as2_id(as2_id)
        if partner and partner.public_cert_pem:
            return partner.public_cert_pem.encode("utf-8")
        return None


class HostIdentityRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _tenant_id(self) -> int:
        tenant_id = get_tenant_id()
        if tenant_id is None:
            raise RuntimeError("Database queries require an active tenant context.")
        return tenant_id

    async def get_host_private_key(self) -> bytes | None:
        """
        Fetches the server's own private key for the current tenant.
        This is required to decrypt inbound messages.
        """
        result = await self.session.execute(
            select(TradingPartner).where(
                TradingPartner.tenant_id == self._tenant_id(),
                TradingPartner.is_host_identity.is_(True),
                TradingPartner.is_active.is_(True),
            )
        )
        host = result.scalar_one_or_none()
        if host and host.private_key_pem:
            return host.private_key_pem.encode("utf-8")
        return None


class AS2PayloadRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _tenant_id(self) -> int:
        tenant_id = get_tenant_id()
        if tenant_id is None:
            raise RuntimeError("Database queries require an active tenant context.")
        return tenant_id

    async def save_payload(
        self,
        message_id: str,
        direction: str,
        as2_from: str,
        as2_to: str,
        status: str,
        payload_storage_uri: str,
        raw_headers: str = None,
        mic: str = None,
    ) -> AS2Payload:
        """
        Persists AS2 payload metadata to PostgreSQL.
        The actual binary payload is stored in S3 (via payload_storage_uri).
        """
        record = AS2Payload(
            tenant_id=self._tenant_id(),
            message_id=message_id,
            direction=direction,
            as2_from=as2_from,
            as2_to=as2_to,
            raw_headers=raw_headers,
            payload_storage_uri=payload_storage_uri,
            status=status,
            mic=mic,
        )
        self.session.add(record)
        await self.session.flush()  # Gets the DB-assigned ID without committing yet
        return record
