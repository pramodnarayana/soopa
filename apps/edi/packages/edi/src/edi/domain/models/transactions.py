from dataclasses import dataclass, replace

from seedwork.models import AggregateRoot, TraceEvent

from edi.domain.enums import EdiDirection, MessageStatus
from edi.domain.events import TransformRequestedEvent
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

    def clone_for_transform_retry(self, new_id: str, new_trace_id: str) -> "EdiJsonDomainModel":
        metadata = dict(self.business_metadata) if self.business_metadata is not None else None
        if metadata is not None:
            metadata.pop("_idempotency_key", None)
        cloned = replace(
            self,
            id=new_id,
            trace_id=new_trace_id,
            parent_trace_id=self.trace_id,
            original_trace_id=self.original_trace_id or self.trace_id,
            replay_count=self.replay_count + 1,
            status=MessageStatus.RECEIVED,
            error_code=None,
            error_details=None,
            status_message=None,
            business_metadata=metadata,
        )
        cloned.clear_domain_events()
        return cloned

    def clone_for_delivery_retry(self, new_id: str, new_trace_id: str) -> "EdiJsonDomainModel":
        metadata = dict(self.business_metadata) if self.business_metadata is not None else None
        if metadata is not None:
            metadata.pop("_idempotency_key", None)
        cloned = replace(
            self,
            id=new_id,
            trace_id=new_trace_id,
            parent_trace_id=self.trace_id,
            original_trace_id=self.original_trace_id or self.trace_id,
            replay_count=self.replay_count + 1,
            status=MessageStatus.PENDING_DELIVERY,
            error_code=None,
            error_details=None,
            status_message=None,
            business_metadata=metadata,
        )
        cloned.clear_domain_events()
        return cloned


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
    mdn_id: str | None = None
    mdn_mode: str | None = None
    mdn_response: str | None = None
    file_name: str | None = None
    content_type: str | None = None
    signature_algorithm: str | None = None
    encryption_algorithm: str | None = None
    state: str | None = None
    msg_headers: str | None = None
    edi_data: str | None = None
    response: str | None = None
    headers: dict[str, JsonValue] | None = None
    storage_uri: str | None = None

    def clone_for_transform_retry(self, new_id: str, new_trace_id: str) -> "EdiMessageDomainModel":
        cloned = replace(
            self,
            id=new_id,
            trace_id=new_trace_id,
            parent_trace_id=self.trace_id,
            original_trace_id=self.original_trace_id or self.trace_id,
            replay_count=self.replay_count + 1,
            status=MessageStatus.RECEIVED,
            error_code=None,
            error_details=None,
            status_message=None,
        )
        cloned.clear_domain_events()
        return cloned

    def clone_for_delivery_retry(self, new_id: str, new_trace_id: str) -> "EdiMessageDomainModel":
        cloned = replace(
            self,
            id=new_id,
            trace_id=new_trace_id,
            parent_trace_id=self.trace_id,
            original_trace_id=self.original_trace_id or self.trace_id,
            replay_count=self.replay_count + 1,
            status=MessageStatus.PENDING_DELIVERY,
            error_code=None,
            error_details=None,
            status_message=None,
        )
        cloned.clear_domain_events()
        return cloned

    def mark_outbound_pending_delivery(
        self,
        *,
        edi_data: str,
        format_standard: str,
        transaction_type: str,
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
            sender_id=sender_id,
            receiver_id=receiver_id,
            gs_sender_id=gs_sender_id,
            gs_receiver_id=gs_receiver_id,
            trading_partner_id=trading_partner_id,
        )
        return instance

    @classmethod
    def create_inbound(
        cls,
        *,
        id: str,
        trace_id: str,
        tenant_id: str,
        edi_data: str,
        status: str,
        trading_partner_id: str,
        sender_id: str,
        receiver_id: str,
        connection_type: str,
        as2_message_id: str | None = None,
    ) -> "EdiMessageDomainModel":
        instance = cls(
            id=id,
            trace_id=trace_id,
            tenant_id=tenant_id,
            direction=EdiDirection.INBOUND,
            status=MessageStatus(status),
            edi_data=edi_data,
            trading_partner_id=trading_partner_id,
            sender_id=sender_id,
            receiver_id=receiver_id,
            connection_type=connection_type,
            message_id=as2_message_id,
        )
        if status == MessageStatus.RECEIVED.value:
            instance.add_domain_event(
                TransformRequestedEvent(
                    trace_id=trace_id,
                    tenant_id=tenant_id,
                    trading_partner_id=trading_partner_id,
                    sender_id=sender_id,
                    receiver_id=receiver_id,
                    direction="INBOUND",
                    edi_message_id=as2_message_id,
                )
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
class TraceEventDomainModel(TraceEvent):
    """Domain model representing an audit trace event in the immutable transaction ledger."""
