from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class UnsetType:
    pass


UNSET = UnsetType()


class EncryptionAlgorithm(StrEnum):
    AES128 = "AES128"
    AES192 = "AES192"
    AES256 = "AES256"
    DES3 = "3DES"
    RC2 = "RC2"


class SignatureAlgorithm(StrEnum):
    SHA1 = "SHA1"
    SHA256 = "SHA256"
    SHA384 = "SHA384"
    SHA512 = "SHA512"
    MD5 = "MD5"


class MDNType(StrEnum):
    SYNC = "SYNC"
    ASYNC = "ASYNC"


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
    name: str | UnsetType = UNSET
    as2_id: str | UnsetType = UNSET
    is_local: bool | UnsetType = UNSET
    url: str | None | UnsetType = UNSET
    public_cert_pem: str | None | UnsetType = UNSET
    public_cert_vault_ref: str | None | UnsetType = UNSET
    private_key_vault_ref: str | None | UnsetType = UNSET
    active: bool | UnsetType = UNSET


@dataclass(frozen=True)
class RotateAS2CertificateCmd:
    action: str | None = None
    public_cert_pem: str | None = None
    private_key_pem: str | None = None
    public_cert_vault_ref: str | None = None
    private_key_vault_ref: str | None = None


@dataclass(frozen=True)
class CreateAS2PartnershipCmd:
    name: str
    local_partner_id: str
    remote_partner_id: str
    local_url: str | None = None
    remote_url: str | None = None
    credentials_vault_ref: str | None = None
    mdn_type: str = "SYNC"
    mdn_url: str | None = None
    encryption_algorithm: str = "AES256"
    signature_algorithm: str = "SHA256"
    advanced_flags: dict[str, Any] | None = None


@dataclass(frozen=True)
class UpdateAS2PartnershipCmd:
    name: str | UnsetType = UNSET
    local_url: str | None | UnsetType = UNSET
    remote_url: str | None | UnsetType = UNSET
    credentials_vault_ref: str | None | UnsetType = UNSET
    mdn_type: str | UnsetType = UNSET
    mdn_url: str | None | UnsetType = UNSET
    encryption_algorithm: str | UnsetType = UNSET
    signature_algorithm: str | UnsetType = UNSET
    advanced_flags: dict[str, Any] | None | UnsetType = UNSET
    active: bool | UnsetType = UNSET


@dataclass(frozen=True)
class CreateSFTPPartnerCmd:
    name: str
    host: str
    username: str
    credentials_vault_ref: str | None = None
    password: str | None = None
    port: int = 22
    inbound_remote_path: str | None = None
    outbound_remote_path: str | None = None


@dataclass(frozen=True)
class UpdateSFTPPartnerCmd:
    name: str | UnsetType = UNSET
    host: str | UnsetType = UNSET
    username: str | UnsetType = UNSET
    password: str | None | UnsetType = UNSET
    credentials_vault_ref: str | UnsetType = UNSET
    port: int | UnsetType = UNSET
    inbound_remote_path: str | None | UnsetType = UNSET
    outbound_remote_path: str | None | UnsetType = UNSET
    active: bool | UnsetType = UNSET


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
    webhook_id: str | None = None
    as2_partner_id: str | None = None
    sftp_partner_id: str | None = None
    name: str | None = None
    trading_partner_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    processing_mode: str | None = None


@dataclass(frozen=True)
class UpdateInboundRouteCmd:
    isa_sender_id: str | UnsetType = UNSET
    isa_receiver_id: str | UnsetType = UNSET
    transaction_type: str | UnsetType = UNSET
    webhook_id: str | None | UnsetType = UNSET
    as2_partner_id: str | None | UnsetType = UNSET
    sftp_partner_id: str | None | UnsetType = UNSET
    active: bool | UnsetType = UNSET
    name: str | None | UnsetType = UNSET
    trading_partner_id: str | UnsetType = UNSET
    gs_sender_id: str | UnsetType = UNSET
    gs_receiver_id: str | UnsetType = UNSET
    processing_mode: str | UnsetType = UNSET


@dataclass(frozen=True)
class CreateOutboundRouteCmd:
    isa_sender_id: str
    isa_receiver_id: str
    transaction_type: str
    as2_partner_id: str | None = None
    sftp_partner_id: str | None = None
    name: str | None = None
    protocol: str | None = None
    trading_partner_id: str | None = None


@dataclass(frozen=True)
class UpdateOutboundRouteCmd:
    isa_sender_id: str | UnsetType = UNSET
    isa_receiver_id: str | UnsetType = UNSET
    transaction_type: str | UnsetType = UNSET
    as2_partner_id: str | None | UnsetType = UNSET
    sftp_partner_id: str | None | UnsetType = UNSET
    active: bool | UnsetType = UNSET
    name: str | None | UnsetType = UNSET
    protocol: str | None | UnsetType = UNSET
    trading_partner_id: str | None | UnsetType = UNSET


# ---------------------------------------------------------------------------
# EDI Header Configuration Commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateOutboundEdiHeaderCmd:
    trading_partner_id: str
    isa_sender_id: str
    isa_receiver_id: str
    name: str | None = None
    isa_sender_qualifier: str | None = None
    isa_receiver_qualifier: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    transaction_type: str | None = None
    default_standard: str | None = None
    default_version: str | None = None


@dataclass(frozen=True)
class UpdateOutboundEdiHeaderCmd:
    trading_partner_id: str | UnsetType = UNSET
    isa_sender_id: str | UnsetType = UNSET
    isa_receiver_id: str | UnsetType = UNSET
    name: str | None | UnsetType = UNSET
    isa_sender_qualifier: str | None | UnsetType = UNSET
    isa_receiver_qualifier: str | None | UnsetType = UNSET
    gs_sender_id: str | None | UnsetType = UNSET
    gs_receiver_id: str | None | UnsetType = UNSET
    transaction_type: str | None | UnsetType = UNSET
    default_standard: str | None | UnsetType = UNSET
    default_version: str | None | UnsetType = UNSET


@dataclass(kw_only=True)
class EdiMessageDTO:
    id: str
    trace_id: str
    direction: str | None = None
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
    status: str | None = None
    edi_data: str | None = None
    interchange_control_no: str | None = None
    transaction_type: str | None = None
    format_standard: str | None = None
    storage_uri: str | None = None
    file_size_bytes: int | None = None
    msg_headers: dict[str, Any] | None = None
    state: str | None = None
    status_message: str | None = None
    is_resend: bool | None = None
    parent_trace_id: str | None = None
    created_at: Any
    updated_at: Any


@dataclass(kw_only=True)
class EdiJsonDTO:
    id: str
    trace_id: str
    status: str | None = None
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
    payload: Any | None = None
    parent_trace_id: str | None = None
    created_at: Any
    updated_at: Any


@dataclass(kw_only=True)
class ApiGatewayDTO:
    id: str
    trace_id: str
    event_type: str | None = None
    status: str | None = None
    error_message: str | None = None
    webhook_url: str | None = None
    http_status_code: int | None = None
    payload: Any | None = None
    response: str | None = None
    parent_trace_id: str | None = None
    created_at: Any
    updated_at: Any


@dataclass(kw_only=True)
class TransactionDetailDTO:
    edi_message: EdiMessageDTO
    edi_jsons: list[EdiJsonDTO]
    api_gateways: list[ApiGatewayDTO]
