from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from seedwork.domain.types import UNSET, JsonValue, UnsetType

# ---------------------------------------------------------------------------
# Domain Enumerations
# ---------------------------------------------------------------------------


class EncryptionAlgorithm(StrEnum):
    AES128 = "AES128"
    AES256 = "AES256"
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
# AS2 Partner Commands
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
    url: str | UnsetType | None = UNSET
    public_cert_pem: str | UnsetType | None = UNSET
    public_cert_vault_ref: str | UnsetType | None = UNSET
    private_key_vault_ref: str | UnsetType | None = UNSET
    active: bool | UnsetType = UNSET


@dataclass(frozen=True)
class RotateAS2CertificateCmd:
    action: str | None = None
    public_cert_pem: str | None = None
    private_key_pem: str | None = None
    public_cert_vault_ref: str | None = None
    private_key_vault_ref: str | None = None


# ---------------------------------------------------------------------------
# AS2 Partnership Commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateAS2PartnershipCmd:
    name: str
    local_partner_id: str
    remote_partner_id: str
    local_url: str | None = None
    remote_url: str | None = None
    credentials_vault_ref: str | None = None
    mdn_type: MDNType = MDNType.SYNC
    mdn_url: str | None = None
    encryption_algorithm: EncryptionAlgorithm = EncryptionAlgorithm.AES256
    signature_algorithm: SignatureAlgorithm = SignatureAlgorithm.SHA256
    advanced_flags: dict[str, JsonValue] | None = None


@dataclass(frozen=True)
class UpdateAS2PartnershipCmd:
    name: str | UnsetType = UNSET
    credentials_vault_ref: str | UnsetType | None = UNSET
    mdn_type: MDNType | UnsetType = UNSET
    mdn_url: str | UnsetType | None = UNSET
    encryption_algorithm: EncryptionAlgorithm | UnsetType = UNSET
    signature_algorithm: SignatureAlgorithm | UnsetType = UNSET
    advanced_flags: dict[str, JsonValue] | UnsetType | None = UNSET
    active: bool | UnsetType = UNSET


# ---------------------------------------------------------------------------
# SFTP Partner Commands
# ---------------------------------------------------------------------------


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
    password: str | UnsetType | None = UNSET
    credentials_vault_ref: str | UnsetType = UNSET
    port: int | UnsetType = UNSET
    inbound_remote_path: str | UnsetType | None = UNSET
    outbound_remote_path: str | UnsetType | None = UNSET
    active: bool | UnsetType = UNSET


# ---------------------------------------------------------------------------
# Webhook Commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateWebhookPartnerCmd:
    name: str
    url: str
    auth_header_vault_ref: str | None = None


# ---------------------------------------------------------------------------
# Inbound Route Commands
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
    webhook_id: str | UnsetType | None = UNSET
    as2_partner_id: str | UnsetType | None = UNSET
    sftp_partner_id: str | UnsetType | None = UNSET
    active: bool | UnsetType = UNSET
    name: str | UnsetType | None = UNSET
    trading_partner_id: str | UnsetType = UNSET
    gs_sender_id: str | UnsetType = UNSET
    gs_receiver_id: str | UnsetType = UNSET
    processing_mode: str | UnsetType = UNSET


# ---------------------------------------------------------------------------
# Outbound Route Commands
# ---------------------------------------------------------------------------


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
    as2_partner_id: str | UnsetType | None = UNSET
    sftp_partner_id: str | UnsetType | None = UNSET
    active: bool | UnsetType = UNSET
    name: str | UnsetType | None = UNSET
    protocol: str | UnsetType | None = UNSET
    trading_partner_id: str | UnsetType | None = UNSET


# ---------------------------------------------------------------------------
# EDI Header Commands
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
    isa_control_version: str | None = None
    isa_usage_indicator: str | None = None
    gs_version: str | None = None
    segment_terminator: str | None = None
    element_separator: str | None = None
    subelement_separator: str | None = None


@dataclass(frozen=True)
class UpdateOutboundEdiHeaderCmd:
    trading_partner_id: str | UnsetType = UNSET
    isa_sender_id: str | UnsetType = UNSET
    isa_receiver_id: str | UnsetType = UNSET
    name: str | UnsetType | None = UNSET
    isa_sender_qualifier: str | UnsetType | None = UNSET
    isa_receiver_qualifier: str | UnsetType | None = UNSET
    gs_sender_id: str | UnsetType | None = UNSET
    gs_receiver_id: str | UnsetType | None = UNSET
    transaction_type: str | UnsetType | None = UNSET
    default_standard: str | UnsetType | None = UNSET
    default_version: str | UnsetType | None = UNSET


# ---------------------------------------------------------------------------
# Pipeline Processing Commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessApiEdiJsonCommand:
    tenant_id: str
    trading_partner_id: str
    payload: JsonValue
    transaction_type: str | None = None


@dataclass(frozen=True)
class ProcessInboundAs2Command:
    headers: dict[str, str]
    body_bytes: bytes
