import uuid
from typing import Protocol


class PartnerEntity:
    def __init__(
        self, as2_id: str, public_cert_pem: str | None = None, active: bool = False
    ) -> None:
        self.as2_id = as2_id
        self.public_cert_pem = public_cert_pem
        self.active = active


class ITradingPartnerRepository(Protocol):
    async def find_by_as2_id(self, tenant_id: str, as2_id: str) -> PartnerEntity | None: ...


class IEdiMessageRepository(Protocol):
    async def save_message(
        self,
        tenant_id: str,
        trace_id: uuid.UUID | str,
        direction: str,
        connection_type: str,
        sender_id: str,
        receiver_id: str,
        edi_data: str,
        status: str,
        as2_message_id: str,
    ) -> None: ...


class IAS2TenantRepository(Protocol):
    async def resolve_tenant_id(self, as2_to: str) -> str | None:
        """Resolves the tenant ID by looking at the global trading partners."""
        ...

    async def resolve_tenant_by_edi_identifiers(
        self, isa_sender: str, isa_receiver: str, transaction_type: str | None = None
    ) -> str | None:
        """
        Resolves the true tenant ID from the global inbound routes using ISA identifiers.
        Raises ValueError if multiple active routes match (ambiguous resolution).
        """
        ...
