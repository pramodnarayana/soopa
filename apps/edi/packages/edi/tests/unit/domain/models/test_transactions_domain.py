"""Pure domain unit tests for EDI transaction aggregates, trace event recording, and replay cloning."""

from __future__ import annotations

import uuid

from strace.domain import TraceEventType

from edi.domain.enums import EdiDirection, MessageStatus
from edi.domain.events import TransformRequestedEvent
from edi.domain.models.transactions import (
    ApiGatewayReceiptDomainModel,
    EdiJsonDomainModel,
    EdiMessageDomainModel,
    TransactionListDomainModel,
)


class TestEdiRecordBaseTraceAndStateTransitions:
    def test_uuid_fields_are_normalized_to_strings_on_init(self) -> None:
        raw_id = uuid.uuid4()
        raw_tenant = uuid.uuid4()
        raw_trace = uuid.uuid4()

        msg = EdiMessageDomainModel(
            id="temp_id",
            tenant_id="temp_tenant",
            trace_id="temp_trace",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.RECEIVED,
        )
        object.__setattr__(msg, "id", raw_id)
        object.__setattr__(msg, "tenant_id", raw_tenant)
        object.__setattr__(msg, "trace_id", raw_trace)
        msg.__post_init__()
        assert msg.id == str(raw_id)
        assert msg.tenant_id == str(raw_tenant)
        assert msg.trace_id == str(raw_trace)

    def test_mark_delivery_attempt_failed_records_trace_event_and_truncates_reason(self) -> None:
        msg = EdiMessageDomainModel(
            id="edi_msg_01",
            tenant_id="ten_01",
            trace_id="trc_01",
            direction=EdiDirection.OUTBOUND,
            status=MessageStatus.PENDING_DELIVERY,
        )
        long_reason = "Connection timed out: " + ("x" * 300)
        msg.mark_delivery_attempt_failed(
            reason=long_reason,
            error_code="HTTP_504",
            error_details={"attempt": 1},
            stack_trace="Traceback...",
        )

        assert msg.status_message is not None
        assert len(msg.status_message) == 255
        assert msg.error_code == "HTTP_504"
        assert msg.error_details == {"attempt": 1}
        assert len(msg.trace_events) == 1
        evt = msg.trace_events[0]
        assert evt.event_type == TraceEventType.DELIVERY_ATTEMPT_FAILED
        assert evt.trace_id == "trc_01"
        assert evt.tenant_id == "ten_01"
        assert evt.metadata is not None
        assert evt.metadata["error_code"] == "HTTP_504"

    def test_mark_delivery_failed_preserves_prior_message_when_max_retries_exceeded(self) -> None:
        msg = EdiMessageDomainModel(
            id="edi_msg_02",
            tenant_id="ten_01",
            trace_id="trc_02",
            direction=EdiDirection.OUTBOUND,
            status=MessageStatus.PENDING_DELIVERY,
            status_message="AS2 MDN signature verification failed",
            error_code="AS2_MDN_ERR",
        )
        msg.mark_delivery_failed(reason="Max delivery retries exceeded.")

        assert msg.status == MessageStatus.FAILED
        assert msg.status_message == "AS2 MDN signature verification failed (Max retries exceeded)"
        assert msg.error_code == "AS2_MDN_ERR"
        assert len(msg.trace_events) == 1
        assert msg.trace_events[0].event_type == TraceEventType.DELIVERY_FAILED

    def test_mark_delivery_failed_direct_reason_and_mark_delivered_clears_errors(self) -> None:
        msg = EdiMessageDomainModel(
            id="edi_msg_03",
            tenant_id="ten_01",
            trace_id="trc_03",
            direction=EdiDirection.OUTBOUND,
            status=MessageStatus.PENDING_DELIVERY,
        )
        msg.mark_delivery_failed(
            reason="Webhook 500 Internal Server Error",
            error_code="WEBHOOK_500",
            error_details={"status_code": 500},
        )
        assert msg.status == MessageStatus.FAILED
        assert msg.error_code == "WEBHOOK_500"

        msg.mark_delivered()
        delivered_status: MessageStatus | None = msg.status
        assert delivered_status == MessageStatus.DELIVERED
        assert msg.status_message is None
        assert msg.error_code is None
        assert msg.error_details is None
        assert [e.event_type for e in msg.trace_events] == [
            TraceEventType.DELIVERY_FAILED,
            TraceEventType.DELIVERY_SUCCESSFUL,
        ]

    def test_mark_transform_failed_and_mark_transformed_and_replay_triggered(self) -> None:
        rec = EdiJsonDomainModel(
            id="edi_json_01",
            tenant_id="ten_01",
            trace_id="trc_04",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.RECEIVED,
        )
        rec.mark_transform_failed(
            reason="BOTS grammar error in segment BEG",
            error_code="BOTS_GRAMMAR",
            error_details={"segment": "BEG"},
        )
        assert rec.status == MessageStatus.FAILED
        assert rec.error_code == "BOTS_GRAMMAR"

        rec.mark_transformed()
        transformed_status: MessageStatus | None = rec.status
        assert transformed_status == MessageStatus.TRANSFORMED
        assert rec.status_message is None
        assert rec.error_code is None
        assert rec.error_details is None

        rec.mark_replay_triggered(actor="ops@soopa.io")
        assert [e.event_type for e in rec.trace_events] == [
            TraceEventType.TRANSFORMATION_FAILED,
            TraceEventType.TRANSFORMATION_SUCCESSFUL,
            TraceEventType.REPLAY_TRIGGERED,
        ]
        assert rec.trace_events[-1].actor == "ops@soopa.io"


class TestEdiAggregateReplayCloningAndFactories:
    def test_edi_json_clone_for_transform_and_delivery_retry_strips_idempotency_key(self) -> None:
        original = EdiJsonDomainModel(
            id="edi_json_root",
            tenant_id="ten_01",
            trace_id="trc_root",
            direction=EdiDirection.OUTBOUND,
            status=MessageStatus.FAILED,
            error_code="ERR_1",
            error_details={"detail": "bad"},
            status_message="Failed",
            business_metadata={"po_number": "PO-100", "_idempotency_key": "idem-123"},
            payload={"BEG03": "PO-100"},
        )
        original.add_domain_event(
            TransformRequestedEvent(
                trace_id="trc_root",
                tenant_id="ten_01",
                direction="OUTBOUND",
            )
        )

        retry_1 = original.clone_for_transform_retry("edi_json_r1", "trc_r1")
        assert retry_1.id == "edi_json_r1"
        assert retry_1.trace_id == "trc_r1"
        assert retry_1.parent_trace_id == "trc_root"
        assert retry_1.original_trace_id == "trc_root"
        assert retry_1.replay_count == 1
        assert retry_1.status == MessageStatus.RECEIVED
        assert retry_1.error_code is None
        assert retry_1.error_details is None
        assert retry_1.status_message is None
        assert retry_1.business_metadata == {"po_number": "PO-100"}
        assert retry_1.domain_events == []

        retry_2 = retry_1.clone_for_delivery_retry("edi_json_r2", "trc_r2")
        assert retry_2.parent_trace_id == "trc_r1"
        assert retry_2.original_trace_id == "trc_root"
        assert retry_2.replay_count == 2
        assert retry_2.status == MessageStatus.PENDING_DELIVERY

    def test_edi_message_clone_and_inbound_outbound_factories(self) -> None:
        inbound = EdiMessageDomainModel.create_inbound(
            id="edi_msg_in_1",
            trace_id="trc_in_1",
            tenant_id="ten_01",
            edi_data="ISA*00*...",
            status=MessageStatus.RECEIVED.value,
            trading_partner_id="tp_01",
            sender_id="SENDER",
            receiver_id="RECEIVER",
            connection_type="AS2",
            as2_message_id="<as2-1@example.com>",
        )
        assert inbound.direction == EdiDirection.INBOUND
        assert inbound.status == MessageStatus.RECEIVED
        assert len(inbound.domain_events) == 1
        assert isinstance(inbound.domain_events[0], TransformRequestedEvent)

        cloned_transform = inbound.clone_for_transform_retry("edi_msg_in_2", "trc_in_2")
        assert cloned_transform.parent_trace_id == "trc_in_1"
        assert cloned_transform.original_trace_id == "trc_in_1"
        assert cloned_transform.replay_count == 1
        assert cloned_transform.status == MessageStatus.RECEIVED
        assert cloned_transform.domain_events == []

        outbound = EdiMessageDomainModel.create_outbound(
            id="edi_msg_out_1",
            trace_id="trc_out_1",
            tenant_id="ten_01",
            edi_data="ISA*00*...",
            format_standard="X12",
            transaction_type="850",
            sender_id="US",
            receiver_id="THEM",
            gs_sender_id="US_GS",
            gs_receiver_id="THEM_GS",
            trading_partner_id="tp_01",
        )
        assert outbound.direction == EdiDirection.OUTBOUND
        assert outbound.status == MessageStatus.PENDING_DELIVERY
        assert outbound.format_standard == "X12"
        assert outbound.transaction_type == "850"

        cloned_deliver = outbound.clone_for_delivery_retry("edi_msg_out_2", "trc_out_2")
        assert cloned_deliver.parent_trace_id == "trc_out_1"
        assert cloned_deliver.original_trace_id == "trc_out_1"
        assert cloned_deliver.replay_count == 1
        assert cloned_deliver.status == MessageStatus.PENDING_DELIVERY

    def test_api_gateway_receipt_and_transaction_list_domain_models(self) -> None:
        receipt = ApiGatewayReceiptDomainModel(
            id="gw_1",
            tenant_id="ten_01",
            trace_id="trc_01",
            direction=EdiDirection.INBOUND,
            status=MessageStatus.SUCCESS,
            http_status_code=200,
            webhook_url="https://webhook.example.com/edi",
        )
        assert receipt.http_status_code == 200

        summary = TransactionListDomainModel(
            trace_id="trc_01",
            transaction_type="850",
            direction="INBOUND",
            trading_partner_id="tp_01",
            status="DELIVERED",
            received_at="2026-10-26T00:00:00Z",
            replay_count=1,
            parent_trace_id="trc_00",
            original_trace_id="trc_00",
        )
        assert summary.replay_count == 1
        assert summary.original_trace_id == "trc_00"
