import uuid
from typing import Protocol


class PartnerEntity:
    def __init__(self, as2_id: str, public_cert_pem: str | None = None) -> None:
        self.as2_id = as2_id
        self.public_cert_pem = public_cert_pem


class ITradingPartnerRepository(Protocol):
    async def find_by_as2_id(self, tenant_id: int, as2_id: str) -> PartnerEntity | None: ...


class IEdiMessageRepository(Protocol):
    async def save_message(
        self,
        tenant_id: int,
        trace_id: uuid.UUID,
        direction: str,
        connection_type: str,
        sender_id: str,
        receiver_id: str,
        s3_key: str,
        status: str,
        as2_message_id: str,
    ) -> None: ...


class IAS2TenantRepository(Protocol):
    async def resolve_tenant_id(self, as2_to: str) -> int | None:
        """Resolves the tenant ID by looking at the global trading partners."""
        ...
