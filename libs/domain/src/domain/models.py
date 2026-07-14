from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EdiJsonDomainModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trace_id: UUID
    direction: str
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
    status: str
    tenant_id: int
    created_at: datetime
    updated_at: datetime


class EdiMessageDomainModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trace_id: UUID
    direction: str
    format_standard: str | None = None
    transaction_type: str | None = None
    status: str
    connection_type: str | None = None
    sender_id: str | None = None
    receiver_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    inbound_route_id: UUID | None = None
    outbound_route_id: UUID | None = None
    tenant_id: int
    edi_data: str | None = None  # Populated from DB or S3
    storage_uri: str | None = None
    created_at: datetime
    updated_at: datetime
