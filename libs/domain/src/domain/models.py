from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Direction(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class RecordStatus(StrEnum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PARSED = "PARSED"
    TRANSFORMED = "TRANSFORMED"
    TRANSLATED = "TRANSLATED"
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
