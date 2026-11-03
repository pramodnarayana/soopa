"""EDI Raw Wire Message Transaction Aggregate Root."""

from __future__ import annotations

from dataclasses import dataclass, replace

from edi.domain.enums import EdiTraceEventType
from edi.domain.routing.enums import EdiDirection
from edi.domain.transaction.enums import MessageStatus
from edi.domain.transaction.events import TransformRequestedEvent
from edi.domain.transaction.record_base import EdiRecordBase
from edi.domain.types import JsonValue

__all__ = ["EdiMessage"]


@dataclass(kw_only=True)
class EdiMessage(EdiRecordBase):
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
    interchange_control_no: str | None = None
    file_size_bytes: int | None = None

    def clone_for_transform_retry(self, new_id: str, new_trace_id: str) -> EdiMessage:
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
        cloned.clear_trace_events()
        return cloned

    def clone_for_delivery_retry(self, new_id: str, new_trace_id: str) -> EdiMessage:
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
        cloned.clear_trace_events()
        return cloned

    def clone_with_modified_payload(
        self,
        *,
        new_id: str,
        new_trace_id: str,
        modified_payload: str,
        actor: str,
    ) -> EdiMessage:
        """Clone with operator-corrected raw EDI payload and record audit traces on both records."""
        root_trace_id = self.original_trace_id or self.trace_id
        is_inbound = self.direction == EdiDirection.INBOUND
        new_msg = EdiMessage(
            id=new_id,
            tenant_id=self.tenant_id,
            trace_id=new_trace_id,
            parent_trace_id=self.trace_id,
            original_trace_id=root_trace_id,
            direction=self.direction,
            status=MessageStatus.RECEIVED if is_inbound else MessageStatus.TRANSFORMED,
            format_standard=self.format_standard,
            transaction_type=self.transaction_type,
            connection_type=self.connection_type,
            sender_id=self.sender_id,
            receiver_id=self.receiver_id,
            gs_sender_id=self.gs_sender_id,
            gs_receiver_id=self.gs_receiver_id,
            trading_partner_id=self.trading_partner_id,
            edi_data=modified_payload,
        )

        if is_inbound:
            new_msg.request_transformation(
                trading_partner_id=new_msg.trading_partner_id,
                sender_id=new_msg.sender_id,
                receiver_id=new_msg.receiver_id,
                edi_message_id=new_msg.id,
            )
            audit_type = EdiTraceEventType.MODIFY_AND_REPLAY_TRANSFORM
        else:
            new_msg.request_delivery(
                trading_partner_id=new_msg.trading_partner_id,
                transaction_type=new_msg.transaction_type,
            )
            audit_type = EdiTraceEventType.MODIFY_AND_REPLAY_DELIVER

        self.record_modified_and_replayed(
            new_trace_id=new_trace_id,
            event_type=audit_type,
            actor=actor,
        )
        new_msg.record_created_from_modification(
            parent_trace_id=self.trace_id,
            original_trace_id=root_trace_id,
            actor=actor,
        )
        return new_msg

    def prepare_bulk_transform_replay(self, *, actor: str, idempotency_key: str) -> None:
        if self.direction == EdiDirection.INBOUND:
            self.request_transformation(
                trading_partner_id=self.trading_partner_id,
                sender_id=self.sender_id,
                receiver_id=self.receiver_id,
                edi_message_id=self.id,
                idempotency_key=idempotency_key,
            )
        self.record_bulk_replay_transform(actor=actor)

    def prepare_bulk_delivery_replay(self, *, actor: str, idempotency_key: str) -> None:
        self.request_delivery(
            trading_partner_id=self.trading_partner_id,
            transaction_type=self.transaction_type,
            idempotency_key=idempotency_key,
        )
        self.record_bulk_replay_deliver(actor=actor)

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
    ) -> EdiMessage:
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
    ) -> EdiMessage:
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
