from dataclasses import dataclass
from typing import Any
from uuid import UUID

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------


class UnsetType:
    pass


UNSET = UnsetType()

# ---------------------------------------------------------------------------
# Partner Creation Commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateAS2TradingPartnerCmd:
    name: str
    as2_id: str
    is_local: bool = False
    url: str | None = None
    public_cert_pem: str | None = None
    public_cert_vault_ref: str | None = None
    private_key_vault_ref: str | None = None


@dataclass(frozen=True)
class UpdateAS2TradingPartnerCmd:
    name: str | None = None
    as2_id: str | None = None
    is_local: bool | None = None
    url: str | None = None
    active: bool | None = None
    public_cert_pem: str | None = None
    public_cert_vault_ref: str | None = None
    private_key_vault_ref: str | None = None


@dataclass(frozen=True)
class CreateAS2PartnershipCmd:
    local_partner_id: UUID
    remote_partner_id: UUID
    name: str
    credentials_vault_ref: str | None = None
    mdn_type: str = "SYNC"
    mdn_url: str | None = None
    encryption_algorithm: str = "AES256"
    signature_algorithm: str = "SHA256"
    edi_version: str | None = None
    advanced_flags: dict[str, Any] | None = None


@dataclass(frozen=True)
class UpdateAS2PartnershipCmd:
    name: str | UnsetType = UNSET
    local_partner_id: UUID | UnsetType = UNSET
    remote_partner_id: UUID | UnsetType = UNSET
    credentials_vault_ref: str | None | UnsetType = UNSET
    mdn_type: str | UnsetType = UNSET
    mdn_url: str | None | UnsetType = UNSET
    encryption_algorithm: str | UnsetType = UNSET
    signature_algorithm: str | UnsetType = UNSET
    edi_version: str | None | UnsetType = UNSET
    advanced_flags: dict[str, Any] | None | UnsetType = UNSET
    active: bool | UnsetType = UNSET


@dataclass(frozen=True)
class CreateSFTPPartnerCmd:
    name: str
    host: str
    username: str
    port: int = 22
    inbound_remote_path: str | None = None
    outbound_remote_path: str | None = None
    password: str | None = None
    credentials_vault_ref: str | None = None


@dataclass(frozen=True)
class UpdateSFTPPartnerCmd:
    name: str | None = None
    host: str | None = None
    port: int | None = None
    username: str | None = None
    credentials_vault_ref: str | None = None
    inbound_remote_path: str | None = None
    outbound_remote_path: str | None = None
    active: bool | None = None
    password: str | None = None


@dataclass(frozen=True)
class CreateWebhookCmd:
    name: str
    url: str
    auth_header_vault_ref: str | None = None


# ---------------------------------------------------------------------------
# Route Creation Commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateInboundRouteCmd:
    name: str
    isa_sender_id: str
    isa_receiver_id: str
    transaction_type: str
    processing_mode: str = "TRANSLATE"
    webhook_partner_id: UUID | None = None
    as2_partner_id: UUID | None = None
    sftp_partner_id: UUID | None = None


@dataclass(frozen=True)
class UpdateInboundRouteCmd:
    name: str | UnsetType = UNSET
    isa_sender_id: str | UnsetType = UNSET
    isa_receiver_id: str | UnsetType = UNSET
    transaction_type: str | UnsetType = UNSET
    processing_mode: str | UnsetType = UNSET
    webhook_partner_id: UUID | None | UnsetType = UNSET
    as2_partner_id: UUID | None | UnsetType = UNSET
    sftp_partner_id: UUID | None | UnsetType = UNSET
    active: bool | UnsetType = UNSET


@dataclass(frozen=True)
class CreateOutboundRouteCmd:
    name: str
    isa_sender_id: str
    isa_receiver_id: str
    transaction_type: str
    processing_mode: str = "TRANSLATE"
    as2_partner_id: UUID | None = None
    sftp_partner_id: UUID | None = None


@dataclass(frozen=True)
class UpdateOutboundRouteCmd:
    name: str | UnsetType = UNSET
    isa_sender_id: str | UnsetType = UNSET
    isa_receiver_id: str | UnsetType = UNSET
    transaction_type: str | UnsetType = UNSET
    processing_mode: str | UnsetType = UNSET
    as2_partner_id: UUID | None | UnsetType = UNSET
    sftp_partner_id: UUID | None | UnsetType = UNSET
    active: bool | UnsetType = UNSET


# ---------------------------------------------------------------------------
# Domain Entities (For Responses)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PartnerEntity:
    partner_id: UUID
    tenant_id: int
    name: str
    type: str  # AS2, SFTP, WEBHOOK
    status: str


@dataclass(frozen=True)
class RouteEntity:
    route_id: UUID
    tenant_id: int
    direction: str  # INBOUND, OUTBOUND
