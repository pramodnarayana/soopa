from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from seedwork.domain.types import JsonDict, JsonValue

from edi.domain.transaction.edi_json import EdiJson
from edi.domain.transaction.edi_message import EdiMessage
from edi.domain.transaction.gateway_receipt import ApiGatewayReceipt


def _parse_msg_headers(raw_headers: str | None) -> JsonDict | None:
    if not raw_headers:
        return None
    parsed = json.loads(raw_headers)
    if isinstance(parsed, dict):
        return cast(JsonDict, parsed)
    return None


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
    error_code: str | None = None
    error_details: JsonDict | None = None
    created_at: datetime
    updated_at: datetime
    replay_count: int = 0
    parent_trace_id: str | None = None
    original_trace_id: str | None = None

    @classmethod
    def from_domain(cls, msg: EdiMessage) -> EdiMessageDTO:
        return cls(
            id=str(msg.id),
            trace_id=str(msg.trace_id),
            direction=msg.direction.value if msg.direction else None,
            connection_type=msg.connection_type,
            sender_id=msg.sender_id,
            receiver_id=msg.receiver_id,
            as2_sender_id=msg.as2_sender_id,
            as2_receiver_id=msg.as2_receiver_id,
            gs_sender_id=msg.gs_sender_id,
            gs_receiver_id=msg.gs_receiver_id,
            message_id=msg.message_id,
            mdn_id=msg.mdn_id,
            mdn_mode=msg.mdn_mode,
            mdn_response=msg.mdn_response,
            file_name=msg.file_name,
            content_type=msg.content_type,
            signature_algorithm=msg.signature_algorithm,
            encryption_algorithm=msg.encryption_algorithm,
            trading_partner_id=msg.trading_partner_id,
            status=msg.status.value if msg.status else None,
            edi_data=msg.edi_data,
            interchange_control_no=msg.interchange_control_no,
            transaction_type=msg.transaction_type,
            format_standard=msg.format_standard,
            storage_uri=msg.storage_uri,
            file_size_bytes=msg.file_size_bytes,
            msg_headers=msg.headers
            if msg.headers is not None
            else _parse_msg_headers(msg.msg_headers),
            state=msg.state,
            status_message=msg.status_message,
            error_code=msg.error_code,
            error_details=msg.error_details,
            created_at=msg.created_at,
            updated_at=msg.updated_at,
            replay_count=msg.replay_count,
            parent_trace_id=msg.parent_trace_id,
            original_trace_id=msg.original_trace_id,
        )


@dataclass(frozen=True, kw_only=True)
class EdiJsonDTO:
    id: str
    trace_id: str
    tenant_id: str | None = None
    direction: str | None = None
    status: str | None = None
    status_message: str | None = None
    error_code: str | None = None
    error_details: JsonDict | None = None
    trading_partner_id: str | None = None
    business_metadata: JsonDict | None = None
    transaction_type: str | None = None
    payload: JsonValue | None = None
    created_at: datetime
    updated_at: datetime
    replay_count: int = 0
    parent_trace_id: str | None = None
    original_trace_id: str | None = None

    @classmethod
    def from_domain(cls, record: EdiJson) -> EdiJsonDTO:
        return cls(
            id=str(record.id),
            trace_id=str(record.trace_id),
            tenant_id=record.tenant_id,
            direction=record.direction.value if record.direction else None,
            status=record.status.value if record.status else None,
            status_message=record.status_message,
            error_code=record.error_code,
            error_details=record.error_details,
            trading_partner_id=record.trading_partner_id,
            business_metadata=record.business_metadata,
            transaction_type=record.transaction_type,
            payload=record.payload,
            created_at=record.created_at,
            updated_at=record.updated_at,
            replay_count=record.replay_count,
            parent_trace_id=record.parent_trace_id,
            original_trace_id=record.original_trace_id,
        )


@dataclass(frozen=True, kw_only=True)
class ApiGatewayDTO:
    id: str
    trace_id: str
    status: str | None = None
    webhook_url: str | None = None
    http_status_code: int | None = None
    payload: JsonValue | None = None
    response: str | None = None
    error_code: str | None = None
    error_details: JsonDict | None = None
    created_at: datetime
    updated_at: datetime
    replay_count: int = 0
    parent_trace_id: str | None = None
    original_trace_id: str | None = None

    @classmethod
    def from_domain(cls, receipt: ApiGatewayReceipt) -> ApiGatewayDTO:
        return cls(
            id=str(receipt.id),
            trace_id=str(receipt.trace_id),
            status=receipt.status.value if receipt.status else None,
            webhook_url=receipt.webhook_url,
            http_status_code=receipt.http_status_code,
            payload=receipt.payload,
            response=receipt.response,
            error_code=receipt.error_code,
            error_details=receipt.error_details,
            created_at=receipt.created_at,
            updated_at=receipt.updated_at,
            replay_count=receipt.replay_count,
            parent_trace_id=receipt.parent_trace_id,
            original_trace_id=receipt.original_trace_id,
        )


@dataclass(frozen=True, kw_only=True)
class EdiTraceDTO:
    """Composed lifecycle view of a full trace: EdiMessage + EdiJson(s) + ApiGateway(s)."""

    edi_message: EdiMessageDTO | None = None
    edi_jsons: tuple[EdiJsonDTO, ...] = ()
    api_gateways: tuple[ApiGatewayDTO, ...] = ()


__all__ = [
    "ApiGatewayDTO",
    "EdiJsonDTO",
    "EdiMessageDTO",
    "EdiTraceDTO",
]
