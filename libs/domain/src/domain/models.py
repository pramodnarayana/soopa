from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Direction(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class ConnectionType(StrEnum):
    AS2 = "AS2"
    SFTP = "SFTP"
    WEBHOOK = "WEBHOOK"
    API = "API"


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


class EdiRecordBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: int
    trace_id: UUID
    direction: Direction
    status: RecordStatus
    created_at: datetime
    updated_at: datetime


class EdiJsonDomainModel(EdiRecordBase):
    outbound_route_id: UUID | None = None
    transaction_type: str | None = None
    standard: str | None = None
    sender_id: str | None = None
    receiver_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    business_metadata: dict[str, Any] | None = None
    payload: dict[str, Any] | list[Any] | None = None
    storage_uri: str | None = None


class EdiMessageDomainModel(EdiRecordBase):
    format_standard: str | None = None
    transaction_type: str | None = None
    connection_type: str | None = None
    sender_id: str | None = None
    receiver_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    inbound_route_id: UUID | None = None
    outbound_route_id: UUID | None = None
    edi_data: str | None = None  # Populated from DB or S3
    storage_uri: str | None = None


class ApiGatewayReceiptDomainModel(EdiRecordBase):
    transaction_type: str | None = None
    webhook_url: str | None = None
    http_status_code: int | None = None
    target_format: str | None = None
    payload: dict[str, Any] | None = None
    storage_uri: str | None = None
    response: str | None = None
    headers: dict[str, Any] | None = None


class WebhookDomainModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: int
    name: str
    url: str
    auth_header_vault_ref: str | None = None
    active: bool
    created_at: datetime
    updated_at: datetime


class AS2PartnerDomainModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: int | None = None
    as2_id: str
    name: str
    public_cert_pem: str | None = None
    public_cert_vault_ref: str | None = None
    private_key_vault_ref: str | None = None
    prev_public_cert_pem: str | None = None
    prev_public_cert_vault_ref: str | None = None
    prev_private_key_vault_ref: str | None = None
    url: str | None = None
    active: bool = False
    is_local: bool
    created_at: datetime
    updated_at: datetime


class AS2PartnershipDomainModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: int | None = None
    name: str
    local_partner_id: UUID
    remote_partner_id: UUID
    credentials_vault_ref: str | None = None
    mdn_type: str
    mdn_url: str | None = None
    encryption_algorithm: str
    signature_algorithm: str
    advanced_flags: dict[str, Any] | None = None
    active: bool = False
    created_at: datetime
    updated_at: datetime


class SFTPPartnerDomainModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: int
    name: str
    host: str
    port: int
    username: str
    host_key: str | None = None
    inbound_remote_path: str | None = None
    outbound_remote_path: str | None = None
    password_encrypted: str | None = None
    credentials_vault_ref: str | None = None
    active: bool
    created_at: datetime
    updated_at: datetime


class InboundRouteDomainModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: int
    name: str
    trading_partner_id: str | None = None
    isa_sender_id: str
    isa_receiver_id: str
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    transaction_type: str | None = None
    processing_mode: ProcessingMode | None = None
    webhook_id: UUID | None = None
    as2_partner_id: UUID | None = None
    sftp_partner_id: UUID | None = None
    active: bool
    created_at: datetime
    updated_at: datetime


class OutboundRouteDomainModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: int
    trading_partner_id: str
    name: str
    protocol: str | None = None
    as2_partner_id: UUID | None = None
    sftp_partner_id: UUID | None = None
    active: bool
    created_at: datetime
    updated_at: datetime


class OutboundEdiHeaderDomainModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: int
    name: str
    trading_partner_id: str
    isa_sender_id: str
    isa_sender_qualifier: str | None = None
    isa_receiver_id: str
    isa_receiver_qualifier: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    transaction_type: str | None = None
    default_standard: str | None = None
    default_version: str | None = None
    created_at: datetime
    updated_at: datetime
