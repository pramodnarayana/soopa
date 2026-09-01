from dataclasses import dataclass
from typing import Any

from seedwork.models import AggregateRoot

from edi.domain.models.base import EdiRecordBase


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
    as2_sender_id: str | None = None
    as2_receiver_id: str | None = None
    message_id: str | None = None
    mdn_mode: str | None = None
    signature_algorithm: str | None = None
    encryption_algorithm: str | None = None
    edi_data: str | None = None
    response: str | None = None
    headers: dict[str, Any] | None = None
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
class TransactionListDomainModel(AggregateRoot):
    trace_id: str
    transaction_type: str | None
    direction: str
    trading_partner_id: str | None
    status: str
    received_at: str
