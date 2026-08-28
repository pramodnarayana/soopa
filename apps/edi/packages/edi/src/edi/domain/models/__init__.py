"""
EDI Domain Models.

This package contains all EDI domain value objects and aggregates.
Sub-modules:
  - as2: AS2 protocol-specific models (AS2Message, AS2MDN, OutboundAS2Message, MDNResponse)
  - outbox_event: Outbox domain event model

All models from the original edi.domain.models flat module are re-exported here
so existing `from edi.domain.models import X` imports remain unchanged.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from seedwork.models import AggregateRoot


class Direction(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class PartnerStatus(StrEnum):
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ConnectionType(StrEnum):
    AS2 = "AS2"
    SFTP = "SFTP"
    WEBHOOK = "WEBHOOK"
    API = "API"
    UNKNOWN = "UNKNOWN"


class ProcessingMode(StrEnum):
    TRANSFORM = "TRANSFORM"
    PASSTHROUGH = "PASSTHROUGH"


class RecordStatus(StrEnum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PARSED = "PARSED"
    TRANSFORMED = "TRANSFORMED"
    PENDING_DELIVERY = "PENDING_DELIVERY"
    DELIVERED = "DELIVERED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ERROR = "ERROR"


@dataclass(kw_only=True)
class EdiRecordBase(AggregateRoot):
    id: str
    tenant_id: str
    trace_id: str
    direction: Direction
    status: RecordStatus
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if isinstance(self.id, UUID):
            self.id = str(self.id)
        if isinstance(self.tenant_id, UUID):
            self.tenant_id = str(self.tenant_id)
        if isinstance(self.trace_id, UUID):
            self.trace_id = str(self.trace_id)


@dataclass(kw_only=True)
class EdiJsonDomainModel(EdiRecordBase):
    trading_partner_id: str | None = None
    transaction_type: str | None = None
    standard: str | None = None
    sender_id: str | None = None
    receiver_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    business_metadata: dict[str, Any] | None = None
    payload: dict[str, Any] | list[Any] | None = None
    storage_uri: str | None = None


@dataclass(kw_only=True)
class EdiMessageDomainModel(EdiRecordBase):
    format_standard: str | None = None
    transaction_type: str | None = None
    connection_type: str | None = None
    sender_id: str | None = None
    receiver_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    inbound_route_id: str | None = None
    trading_partner_id: str | None = None
    edi_data: str | None = None
    storage_uri: str | None = None


@dataclass(kw_only=True)
class ApiGatewayReceiptDomainModel(EdiRecordBase):
    transaction_type: str | None = None
    webhook_url: str | None = None
    http_status_code: int | None = None
    target_format: str | None = None
    payload: dict[str, Any] | None = None
    storage_uri: str | None = None
    response: str | None = None
    headers: dict[str, Any] | None = None


@dataclass(kw_only=True)
class WebhookDomainModel(AggregateRoot):
    id: str
    tenant_id: str
    name: str
    url: str
    active: bool
    created_at: datetime
    updated_at: datetime
    auth_header_vault_ref: str | None = None


@dataclass(kw_only=True)
class AS2PartnerDomainModel(AggregateRoot):
    id: str
    as2_id: str
    name: str
    is_local: bool
    created_at: datetime
    updated_at: datetime
    tenant_id: str | None = None
    public_cert_pem: str | None = None
    public_cert_vault_ref: str | None = None
    private_key_vault_ref: str | None = None
    prev_public_cert_pem: str | None = None
    prev_public_cert_vault_ref: str | None = None
    prev_private_key_vault_ref: str | None = None
    url: str | None = None
    active: bool = False


@dataclass(kw_only=True)
class AS2PartnershipDomainModel(AggregateRoot):
    id: str
    name: str
    local_partner_id: str
    remote_partner_id: str
    mdn_type: str
    encryption_algorithm: str
    signature_algorithm: str
    created_at: datetime
    updated_at: datetime
    tenant_id: str | None = None
    credentials_vault_ref: str | None = None
    mdn_url: str | None = None
    advanced_flags: dict[str, Any] | None = None
    active: bool = False


@dataclass(kw_only=True)
class SFTPPartnerDomainModel(AggregateRoot):
    id: str
    tenant_id: str
    name: str
    host: str
    port: int
    username: str
    active: bool
    created_at: datetime
    updated_at: datetime
    host_key: str | None = None
    inbound_remote_path: str | None = None
    outbound_remote_path: str | None = None
    password_encrypted: str | None = None
    credentials_vault_ref: str | None = None
    deleted_at: datetime | None = None


@dataclass(kw_only=True)
class InboundRouteDomainModel(AggregateRoot):
    id: str
    tenant_id: str
    name: str
    isa_sender_id: str
    isa_receiver_id: str
    active: bool
    created_at: datetime
    updated_at: datetime
    trading_partner_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    transaction_type: str | None = None
    processing_mode: ProcessingMode | None = None
    webhook_id: str | None = None
    as2_partner_id: str | None = None
    sftp_partner_id: str | None = None
    direction: str = "INBOUND"
    destination_name: str | None = None


@dataclass(kw_only=True)
class OutboundRouteDomainModel(AggregateRoot):
    id: str
    tenant_id: str
    trading_partner_id: str
    name: str
    active: bool
    created_at: datetime
    updated_at: datetime
    protocol: str | None = None
    as2_partner_id: str | None = None
    sftp_partner_id: str | None = None
    direction: str = "OUTBOUND"
    destination_name: str | None = None


@dataclass(kw_only=True)
class OutboundEdiHeaderDomainModel(AggregateRoot):
    id: str
    tenant_id: str
    name: str
    trading_partner_id: str
    isa_sender_id: str
    isa_receiver_id: str
    created_at: datetime
    updated_at: datetime
    isa_sender_qualifier: str | None = None
    isa_receiver_qualifier: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    transaction_type: str | None = None
    default_standard: str | None = None
    default_version: str | None = None


@dataclass(kw_only=True)
class TransactionListDomainModel(AggregateRoot):
    trace_id: str
    transaction_type: str | None
    direction: str
    trading_partner_id: str | None
    status: str
    received_at: str
