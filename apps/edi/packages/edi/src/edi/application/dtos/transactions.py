from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from seedwork.domain.types import JsonValue


@dataclass(frozen=True, kw_only=True)
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
    trading_partner_id: str | None = None
    status: str | None = None
    edi_data: str | None = None
    interchange_control_no: str | None = None
    transaction_type: str | None = None
    format_standard: str | None = None
    storage_uri: str | None = None
    file_size_bytes: int | None = None
    msg_headers: dict[str, JsonValue] | None = None
    state: str | None = None
    status_message: str | None = None
    is_resend: bool | None = None
    parent_trace_id: str | None = None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, kw_only=True)
class EdiJsonDTO:
    id: str
    trace_id: str
    tenant_id: str | None = None
    direction: str | None = None
    status: str | None = None
    trading_partner_id: str | None = None
    business_metadata: dict[str, JsonValue] | None = None
    transaction_type: str | None = None
    sender_id: str | None = None
    receiver_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    payload: JsonValue | None = None
    parent_trace_id: str | None = None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, kw_only=True)
class ApiGatewayDTO:
    id: str
    trace_id: str
    status: str | None = None
    webhook_url: str | None = None
    http_status_code: int | None = None
    payload: JsonValue | None = None
    response: str | None = None
    parent_trace_id: str | None = None
    created_at: datetime
    updated_at: datetime
