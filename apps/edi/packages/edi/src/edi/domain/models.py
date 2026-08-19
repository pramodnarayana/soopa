from dataclasses import dataclass
from datetime import datetime

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------
from enum import StrEnum
from typing import Any, Literal

from domain.models import ConnectionType, Direction, PartnerStatus


class MDNType(StrEnum):
    SYNC = "SYNC"
    ASYNC = "ASYNC"


class EncryptionAlgorithm(StrEnum):
    AES128 = "AES128"
    AES192 = "AES192"
    AES256 = "AES256"
    DES3 = "3DES"
    NONE = "NONE"


class SignatureAlgorithm(StrEnum):
    SHA1 = "SHA1"
    SHA224 = "SHA224"
    SHA256 = "SHA256"
    SHA384 = "SHA384"
    SHA512 = "SHA512"
    NONE = "NONE"


class UnsetType:
    def __repr__(self) -> str:
        return "UNSET"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, UnsetType)

    def __hash__(self) -> int:
        return hash("UNSET")

    def __copy__(self) -> "UnsetType":
        return self

    def __deepcopy__(self, memo: Any) -> "UnsetType":
        return self


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
    private_key_pem: str | None = None
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
class RotateAS2CertificateCmd:
    action: Literal["generate", "upload"]
    public_cert_pem: str | None = None
    private_key_pem: str | None = None


@dataclass(frozen=True)
class CreateAS2PartnershipCmd:
    local_partner_id: str
    remote_partner_id: str
    name: str
    trading_partner_id: str | None = None
    credentials_vault_ref: str | None = None
    mdn_type: MDNType = MDNType.SYNC
    mdn_url: str | None = None
    encryption_algorithm: EncryptionAlgorithm = EncryptionAlgorithm.AES256
    signature_algorithm: SignatureAlgorithm = SignatureAlgorithm.SHA256

    advanced_flags: dict[str, Any] | None = None


@dataclass(frozen=True)
class UpdateAS2PartnershipCmd:
    name: str | UnsetType = UNSET
    local_partner_id: str | UnsetType = UNSET
    remote_partner_id: str | UnsetType = UNSET
    credentials_vault_ref: str | UnsetType | None = UNSET
    mdn_type: MDNType | UnsetType = UNSET
    mdn_url: str | UnsetType | None = UNSET
    encryption_algorithm: EncryptionAlgorithm | UnsetType = UNSET
    signature_algorithm: SignatureAlgorithm | UnsetType = UNSET

    advanced_flags: dict[str, Any] | UnsetType | None = UNSET
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
    host_key: str | None = None


@dataclass(frozen=True)
class UpdateSFTPPartnerCmd:
    name: str | UnsetType | None = UNSET
    host: str | UnsetType | None = UNSET
    port: int | UnsetType | None = UNSET
    username: str | UnsetType | None = UNSET
    credentials_vault_ref: str | UnsetType | None = UNSET
    inbound_remote_path: str | UnsetType | None = UNSET
    outbound_remote_path: str | UnsetType | None = UNSET
    active: bool | UnsetType | None = UNSET
    password: str | UnsetType | None = UNSET
    host_key: str | UnsetType | None = UNSET


# ---------------------------------------------------------------------------
# Route Creation Commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateInboundRouteCmd:
    name: str
    isa_sender_id: str
    isa_receiver_id: str
    transaction_type: str
    trading_partner_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    processing_mode: str = "TRANSFORM"
    webhook_id: str | None = None
    as2_partner_id: str | None = None
    sftp_partner_id: str | None = None


@dataclass(frozen=True)
class UpdateInboundRouteCmd:
    name: str | UnsetType = UNSET
    trading_partner_id: str | UnsetType | None = UNSET
    isa_sender_id: str | UnsetType = UNSET
    isa_receiver_id: str | UnsetType = UNSET
    gs_sender_id: str | UnsetType | None = UNSET
    gs_receiver_id: str | UnsetType | None = UNSET
    transaction_type: str | UnsetType = UNSET
    processing_mode: str | UnsetType = UNSET
    webhook_id: str | UnsetType | None = UNSET
    as2_partner_id: str | UnsetType | None = UNSET
    sftp_partner_id: str | UnsetType | None = UNSET
    active: bool | UnsetType = UNSET


@dataclass(frozen=True)
class CreateOutboundRouteCmd:
    trading_partner_id: str
    name: str
    as2_partner_id: str | None = None
    sftp_partner_id: str | None = None


@dataclass(frozen=True)
class UpdateOutboundRouteCmd:
    trading_partner_id: str | UnsetType | None = UNSET
    name: str | UnsetType = UNSET
    as2_partner_id: str | UnsetType | None = UNSET
    sftp_partner_id: str | UnsetType | None = UNSET
    active: bool | UnsetType = UNSET


@dataclass(frozen=True)
class CreateOutboundEdiHeaderCmd:
    name: str
    trading_partner_id: str
    isa_sender_id: str
    isa_receiver_id: str
    gs_sender_id: str
    gs_receiver_id: str
    transaction_type: str
    isa_sender_qualifier: str | None = None
    isa_receiver_qualifier: str | None = None
    default_standard: str = "x12"
    default_version: str = "004010"


@dataclass(frozen=True)
class UpdateOutboundEdiHeaderCmd:
    name: str | UnsetType | None = UNSET
    trading_partner_id: str | UnsetType | None = UNSET
    isa_sender_id: str | UnsetType = UNSET
    isa_sender_qualifier: str | UnsetType | None = UNSET
    isa_receiver_id: str | UnsetType = UNSET
    isa_receiver_qualifier: str | UnsetType | None = UNSET
    gs_sender_id: str | UnsetType = UNSET
    gs_receiver_id: str | UnsetType = UNSET
    transaction_type: str | UnsetType = UNSET
    default_standard: str | UnsetType = UNSET
    default_version: str | UnsetType = UNSET


# ---------------------------------------------------------------------------
# Domain Entities (For Responses)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PartnerEntity:
    partner_id: str
    tenant_id: str
    name: str
    type: ConnectionType
    status: PartnerStatus


@dataclass(frozen=True)
class RouteEntity:
    route_id: str
    tenant_id: str
    direction: Direction


@dataclass(frozen=True)
class BaseRouteListEntity:
    route_id: str
    name: str
    trading_partner_id: str | None
    destination_type: str
    destination_name: str
    webhook_id: str | None
    as2_partner_id: str | None
    sftp_partner_id: str | None
    active: bool


@dataclass(frozen=True)
class InboundRouteListEntity(BaseRouteListEntity):
    direction: Direction
    isa_sender_id: str
    isa_receiver_id: str
    gs_sender_id: str | None
    gs_receiver_id: str | None
    transaction_type: str | None


@dataclass(frozen=True)
class OutboundRouteListEntity(BaseRouteListEntity):
    direction: Direction
    transaction_type: str
    isa_sender_id: str | None
    isa_receiver_id: str | None


# ---------------------------------------------------------------------------
# API Token Commands & Entities
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApiTokenListEntity:
    id: str
    name: str
    client_id: str
    active: bool
    last_used_at: str | None
    expires_at: str | None
    created_at: str


@dataclass(frozen=True)
class CreateApiTokenCmd:
    name: str
    expires_at: datetime | None = None


@dataclass(frozen=True)
class ApiTokenEntity:
    """Returned once after creation. client_secret is shown only this time."""

    id: str
    tenant_id: str
    name: str
    client_id: str  # stored plaintext, safe to display in UI
    client_secret: str  # shown once, never stored — only its hash is in DB
    active: bool


@dataclass(frozen=True)
class EdiMessageDTO:
    id: str
    trace_id: str
    direction: str
    connection_type: str | None = None
    sender_id: str | None = None
    receiver_id: str | None = None
    as2_sender_id: str | None = None
    as2_receiver_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    message_id: str | None = None
    mdn_id: str | None = None
    mdn_mode: str | None = None
    mdn_response: str | None = None
    file_name: str | None = None
    content_type: str | None = None
    signature_algorithm: str | None = None
    encryption_algorithm: str | None = None
    compression: str | None = None
    inbound_route_id: str | None = None
    trading_partner_id: str | None = None
    status: str = "RECEIVED"
    edi_data: str | None = None
    interchange_control_no: str | None = None
    transaction_type: str | None = None
    format_standard: str | None = None
    storage_uri: str | None = None
    file_size_bytes: int | None = None
    msg_headers: dict[str, Any] | None = None
    state: str | None = None
    status_message: str | None = None
    is_resend: bool = False
    parent_trace_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class EdiJsonDTO:
    id: str
    trace_id: str
    status: str
    trading_partner_id: str | None = None
    error_message: str | None = None
    interchange_control_number: str | None = None
    group_control_number: str | None = None
    transaction_set_control_number: str | None = None
    business_metadata: dict[str, Any] | None = None
    processing_metadata: dict[str, Any] | None = None
    transaction_type: str | None = None
    sender_id: str | None = None
    receiver_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    payload: dict[str, Any] | None = None
    parent_trace_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class ApiGatewayDTO:
    id: str
    trace_id: str
    event_type: str | None = None
    status: str | None = None
    error_message: str | None = None
    webhook_url: str | None = None
    http_status_code: int | None = None
    payload: dict[str, Any] | None = None
    response: dict[str, Any] | None = None
    parent_trace_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class TransactionDetailDTO:
    edi_message: EdiMessageDTO | None = None
    edi_jsons: list[EdiJsonDTO] | None = None
    api_gateways: list[ApiGatewayDTO] | None = None
