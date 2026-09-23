from dataclasses import dataclass

from seedwork.models import AggregateRoot

from edi.domain.enums import EdiDirection, MessageStatus
from edi.domain.models.base import EdiRecordBase
from edi.domain.types import JsonValue


@dataclass(kw_only=True)
class EdiJsonDomainModel(EdiRecordBase):
    trading_partner_id: str | None = None
    transaction_type: str | None = None
    standard: str | None = None
    business_metadata: dict[str, JsonValue] | None = None
    payload: JsonValue | None = None
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
    trading_partner_id: str | None = None
    as2_sender_id: str | None = None
    as2_receiver_id: str | None = None
    message_id: str | None = None
    mdn_mode: str | None = None
    signature_algorithm: str | None = None
    encryption_algorithm: str | None = None
    edi_data: str | None = None
    response: str | None = None
    headers: dict[str, JsonValue] | None = None
    storage_uri: str | None = None

    def mark_outbound_pending_delivery(
        self,
        *,
        edi_data: str,
        format_standard: str,
        transaction_type: str,
        connection_type: str,
        sender_id: str,
        receiver_id: str,
        gs_sender_id: str | None,
        gs_receiver_id: str | None,
        trading_partner_id: str | None,
    ) -> None:
        """Encapsulates the outbound EDI transform completion state transition.

        Applies all field updates produced by the BOTS transformer and advances
        the aggregate to PENDING_DELIVERY in a single, intent-revealing operation.
        Use cases MUST call this method instead of directly mutating individual fields.
        """
        self.edi_data = edi_data
        self.format_standard = format_standard
        self.transaction_type = transaction_type
        self.status = MessageStatus.PENDING_DELIVERY
        self.connection_type = connection_type
        self.sender_id = sender_id
        self.receiver_id = receiver_id
        self.gs_sender_id = gs_sender_id
        self.gs_receiver_id = gs_receiver_id
        self.trading_partner_id = trading_partner_id

    @classmethod
    def create_outbound(
        cls,
        *,
        id: str,
        trace_id: str,
        tenant_id: str,
        replay_count: int = 0,
        parent_trace_id: str | None = None,
        original_trace_id: str | None = None,
        edi_data: str,
        format_standard: str,
        transaction_type: str,
        connection_type: str,
        sender_id: str,
        receiver_id: str,
        gs_sender_id: str | None,
        gs_receiver_id: str | None,
        trading_partner_id: str | None,
    ) -> "EdiMessageDomainModel":
        """Factory for creating a new outbound EDI message aggregate.

        Constructs the aggregate in the correct initial state (PENDING_DELIVERY) and
        applies all transform-produced fields via mark_outbound_pending_delivery() in
        a single, atomic operation. Callers must never use the raw constructor +
        mark_outbound_pending_delivery() combination for new outbound entities.
        """
        instance = cls(
            id=id,
            trace_id=trace_id,
            tenant_id=tenant_id,
            direction=EdiDirection.OUTBOUND,
            status=MessageStatus.PENDING_DELIVERY,
            replay_count=replay_count,
            parent_trace_id=parent_trace_id,
            original_trace_id=original_trace_id,
        )
        instance.mark_outbound_pending_delivery(
            edi_data=edi_data,
            format_standard=format_standard,
            transaction_type=transaction_type,
            connection_type=connection_type,
            sender_id=sender_id,
            receiver_id=receiver_id,
            gs_sender_id=gs_sender_id,
            gs_receiver_id=gs_receiver_id,
            trading_partner_id=trading_partner_id,
        )
        return instance


@dataclass(kw_only=True)
class ApiGatewayReceiptDomainModel(EdiRecordBase):
    transaction_type: str | None = None
    webhook_url: str | None = None
    http_status_code: int | None = None
    target_format: str | None = None
    payload: JsonValue | None = None
    storage_uri: str | None = None
    response: str | None = None
    headers: dict[str, JsonValue] | None = None


@dataclass(kw_only=True)
class TransactionListDomainModel(AggregateRoot):
    trace_id: str
    transaction_type: str | None
    direction: str
    trading_partner_id: str | None
    status: str
    received_at: str
    replay_count: int = 0
    parent_trace_id: str | None = None
    original_trace_id: str | None = None


@dataclass(kw_only=True)
class TraceEventDomainModel:
    id: str
    tenant_id: str
    trace_id: str
    event_type: str
    actor: str
    metadata: dict[str, JsonValue] | None = None
