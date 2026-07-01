from dataclasses import dataclass
from typing import Any
from uuid import UUID

# ---------------------------------------------------------------------------
# Partner Creation Commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateAS2TradingPartnerCmd:
    name: str
    as2_id: str
    is_local: bool = False
    public_cert_pem: str | None = None
    public_cert_vault_ref: str | None = None
    private_key_vault_ref: str | None = None


@dataclass(frozen=True)
class CreateAS2PartnershipCmd:
    local_partner_id: UUID
    remote_partner_id: UUID
    local_url: str | None = None
    remote_url: str | None = None
    credentials_vault_ref: str | None = None
    mdn_type: str = "SYNC"
    mdn_url: str | None = None
    encryption_algorithm: str = "AES256"
    signature_algorithm: str = "SHA256"
    edi_version: str | None = None
    advanced_flags: dict[str, Any] | None = None


@dataclass(frozen=True)
class CreateSFTPPartnerCmd:
    name: str
    host: str
    username: str
    credentials_vault_ref: str
    port: int = 22
    remote_path: str | None = None


@dataclass(frozen=True)
class CreateWebhookPartnerCmd:
    name: str
    url: str
    auth_header_vault_ref: str | None = None


# ---------------------------------------------------------------------------
# Route Creation Commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateInboundRouteCmd:
    isa_sender_id: str
    isa_receiver_id: str
    transaction_type: str
    webhook_partner_id: UUID | None = None
    as2_partner_id: UUID | None = None
    sftp_partner_id: UUID | None = None


@dataclass(frozen=True)
class CreateOutboundRouteCmd:
    isa_sender_id: str
    isa_receiver_id: str
    transaction_type: str
    as2_partner_id: UUID | None = None
    sftp_partner_id: UUID | None = None


# ---------------------------------------------------------------------------
# Domain Entities (For Responses)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PartnerEntity:
    partner_id: UUID
    tenant_id: int
    type: str  # AS2, SFTP, WEBHOOK
    status: str


@dataclass(frozen=True)
class RouteEntity:
    route_id: UUID
    tenant_id: int
    direction: str  # INBOUND, OUTBOUND
