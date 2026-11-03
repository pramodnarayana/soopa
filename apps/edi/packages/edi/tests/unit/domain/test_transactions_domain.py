"""Pure domain unit tests for EDI transaction aggregates, trace event recording, and replay cloning."""

from __future__ import annotations

import uuid

from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from edi.domain.constants import EdiIdPrefix
from edi.domain.enums import EdiTraceEventType
from edi.domain.routing.enums import EdiDirection
from edi.domain.transaction.edi_json import EdiJson
from edi.domain.transaction.edi_message import EdiMessage
from edi.domain.transaction.enums import MessageStatus
from edi.domain.transaction.events import (
    DeliverRequestedEvent,
    DeliveryFailed,
    DeliverySuccessful,
    TransformFailed,
    TransformRequestedEvent,
    TransformSuccessful,
)
from edi.domain.transaction.gateway_receipt import ApiGatewayReceipt


class TestEdiRecordBaseTraceAndStateTransitions:
    def test_uuid_fields_are_normalized_to_strings_on_init(self) -> None:
        raw_id = uuid.uuid4()
        raw_tenant = uuid.uuid4()
        raw_trace = uuid.uuid4()

        msg = EdiMessage(
            id=generate_id(EdiIdPrefix.EDI_MESSAGE),
            tenant_id=generate_id(EdiIdPrefix.TENANT),
            trace_id=generate_id(SystemIdPrefix.TRACE),
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
        tenant_id = generate_id(EdiIdPrefix.TENANT)
        trace_id = generate_id(SystemIdPrefix.TRACE)
        msg = EdiMessage(
            id=generate_id(EdiIdPrefix.EDI_MESSAGE),
            tenant_id=tenant_id,
            trace_id=trace_id,
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
        assert evt.event_type == EdiTraceEventType.DELIVERY_ATTEMPT_FAILED
        assert evt.trace_id == trace_id
        assert evt.tenant_id == tenant_id
        assert evt.metadata is not None
        assert evt.metadata["error_code"] == "HTTP_504"

    def test_mark_delivery_failed_preserves_prior_message_when_max_retries_exceeded(self) -> None:
        msg = EdiMessage(
            id=generate_id(EdiIdPrefix.EDI_MESSAGE),
            tenant_id=generate_id(EdiIdPrefix.TENANT),
            trace_id=generate_id(SystemIdPrefix.TRACE),
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
        assert msg.trace_events[0].event_type == EdiTraceEventType.DELIVERY_FAILED

    def test_mark_delivery_failed_direct_reason_and_mark_delivered_clears_errors(self) -> None:
        msg = EdiMessage(
            id=generate_id(EdiIdPrefix.EDI_MESSAGE),
            tenant_id=generate_id(EdiIdPrefix.TENANT),
            trace_id=generate_id(SystemIdPrefix.TRACE),
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
            EdiTraceEventType.DELIVERY_FAILED,
            EdiTraceEventType.DELIVERY_SUCCESSFUL,
        ]

    def test_mark_transform_failed_and_mark_transformed_and_replay_triggered(self) -> None:
        rec = EdiJson(
            id=generate_id(EdiIdPrefix.EDI_JSON),
            tenant_id=generate_id(EdiIdPrefix.TENANT),
            trace_id=generate_id(SystemIdPrefix.TRACE),
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
            EdiTraceEventType.TRANSFORMATION_FAILED,
            EdiTraceEventType.TRANSFORMATION_SUCCESSFUL,
            EdiTraceEventType.REPLAY_TRIGGERED,
        ]
        assert rec.trace_events[-1].actor == "ops@soopa.io"


class TestEdiAggregateReplayCloningAndFactories:
    def test_edi_json_clone_for_transform_and_delivery_retry_strips_idempotency_key(self) -> None:
        tenant_id = generate_id(EdiIdPrefix.TENANT)
        root_id = generate_id(EdiIdPrefix.EDI_JSON)
        root_trace = generate_id(SystemIdPrefix.TRACE)
        partner_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER)
        idem_key = generate_id(SystemIdPrefix.IDEMPOTENCY)
        r1_id = generate_id(EdiIdPrefix.EDI_JSON)
        r1_trace = generate_id(SystemIdPrefix.TRACE)
        r2_id = generate_id(EdiIdPrefix.EDI_JSON)
        r2_trace = generate_id(SystemIdPrefix.TRACE)

        original = EdiJson(
            id=root_id,
            tenant_id=tenant_id,
            trace_id=root_trace,
            direction=EdiDirection.OUTBOUND,
            status=MessageStatus.FAILED,
            error_code="ERR_1",
            error_details={"detail": "bad"},
            status_message="Failed",
            business_metadata={"po_number": "PO-100", "_idempotency_key": idem_key},
            payload={"BEG03": "PO-100"},
        )
        original.request_transformation(trading_partner_id=partner_id)

        retry_1 = original.clone_for_transform_retry(r1_id, r1_trace)
        assert retry_1.id == r1_id
        assert retry_1.trace_id == r1_trace
        assert retry_1.parent_trace_id == root_trace
        assert retry_1.original_trace_id == root_trace
        assert retry_1.replay_count == 1
        assert retry_1.status == MessageStatus.RECEIVED
        assert retry_1.error_code is None
        assert retry_1.error_details is None
        assert retry_1.status_message is None
        assert retry_1.business_metadata == {"po_number": "PO-100"}
        assert retry_1.domain_events == []

        retry_2 = retry_1.clone_for_delivery_retry(r2_id, r2_trace)
        assert retry_2.parent_trace_id == r1_trace
        assert retry_2.original_trace_id == root_trace
        assert retry_2.replay_count == 2
        assert retry_2.status == MessageStatus.PENDING_DELIVERY

    def test_edi_message_clone_and_inbound_outbound_factories(self) -> None:
        tenant_id = generate_id(EdiIdPrefix.TENANT)
        partner_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER)
        in_id_1 = generate_id(EdiIdPrefix.EDI_MESSAGE)
        in_trace_1 = generate_id(SystemIdPrefix.TRACE)
        in_id_2 = generate_id(EdiIdPrefix.EDI_MESSAGE)
        in_trace_2 = generate_id(SystemIdPrefix.TRACE)
        out_id_1 = generate_id(EdiIdPrefix.EDI_MESSAGE)
        out_trace_1 = generate_id(SystemIdPrefix.TRACE)
        out_id_2 = generate_id(EdiIdPrefix.EDI_MESSAGE)
        out_trace_2 = generate_id(SystemIdPrefix.TRACE)

        inbound = EdiMessage.create_inbound(
            id=in_id_1,
            trace_id=in_trace_1,
            tenant_id=tenant_id,
            edi_data="ISA*00*...",
            status=MessageStatus.RECEIVED.value,
            trading_partner_id=partner_id,
            sender_id="SENDER",
            receiver_id="RECEIVER",
            connection_type="AS2",
            as2_message_id="<as2-1@example.com>",
        )
        assert inbound.direction == EdiDirection.INBOUND
        assert inbound.status == MessageStatus.RECEIVED
        assert len(inbound.domain_events) == 1
        assert isinstance(inbound.domain_events[0], TransformRequestedEvent)

        cloned_transform = inbound.clone_for_transform_retry(in_id_2, in_trace_2)
        assert cloned_transform.parent_trace_id == in_trace_1
        assert cloned_transform.original_trace_id == in_trace_1
        assert cloned_transform.replay_count == 1
        assert cloned_transform.status == MessageStatus.RECEIVED
        assert cloned_transform.domain_events == []

        outbound = EdiMessage.create_outbound(
            id=out_id_1,
            trace_id=out_trace_1,
            tenant_id=tenant_id,
            edi_data="ISA*00*...",
            format_standard="X12",
            transaction_type="850",
            sender_id="US",
            receiver_id="THEM",
            gs_sender_id="US_GS",
            gs_receiver_id="THEM_GS",
            trading_partner_id=partner_id,
        )
        assert outbound.direction == EdiDirection.OUTBOUND
        assert outbound.status == MessageStatus.PENDING_DELIVERY
        assert outbound.format_standard == "X12"
        assert outbound.transaction_type == "850"

        cloned_deliver = outbound.clone_for_delivery_retry(out_id_2, out_trace_2)
        assert cloned_deliver.parent_trace_id == out_trace_1
        assert cloned_deliver.original_trace_id == out_trace_1
        assert cloned_deliver.replay_count == 1
        assert cloned_deliver.status == MessageStatus.PENDING_DELIVERY

    def test_api_gateway_receipt(self) -> None:
        receipt = ApiGatewayReceipt(
            id=generate_id(EdiIdPrefix.EDI_API_GATEWAY),
            tenant_id=generate_id(EdiIdPrefix.TENANT),
            trace_id=generate_id(SystemIdPrefix.TRACE),
            direction=EdiDirection.INBOUND,
            status=MessageStatus.SUCCESS,
            http_status_code=200,
            webhook_url="https://webhook.example.com/edi",
        )
        assert receipt.http_status_code == 200

    def test_behavioral_pipeline_event_recording_methods(self) -> None:
        tenant_id = generate_id(EdiIdPrefix.TENANT)
        partner_id = generate_id(EdiIdPrefix.EDI_AS2_PARTNER)
        idem_tx = generate_id(SystemIdPrefix.IDEMPOTENCY)
        idem_del = generate_id(SystemIdPrefix.IDEMPOTENCY)

        msg = EdiMessage(
            id=generate_id(EdiIdPrefix.EDI_MESSAGE),
            tenant_id=tenant_id,
            trace_id=generate_id(SystemIdPrefix.TRACE),
            direction=EdiDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            trading_partner_id=partner_id,
            sender_id="SND",
            receiver_id="RCV",
            transaction_type="850",
        )
        msg.record_received(as2_sender="AS2_SND")
        msg.request_transformation(edi_message_id=msg.id, idempotency_key=idem_tx)
        events = msg.pull_domain_events()
        assert len(events) == 1
        assert isinstance(events[0], TransformRequestedEvent)
        assert events[0].idempotency_key == idem_tx

        msg.complete_transformation(
            isa_sender_id="SND",
            isa_receiver_id="RCV",
            gs_sender_id="GS_S",
            gs_receiver_id="GS_R",
            transaction_type="850",
        )
        assert msg.status == MessageStatus.TRANSFORMED
        tx_ok_events = msg.pull_domain_events()
        assert len(tx_ok_events) == 1
        assert isinstance(tx_ok_events[0], TransformSuccessful)

        # Stateless parent-record event emission must NOT mutate status or trace_events
        trace_count_before = len(msg.trace_events)
        msg.record_delivery_succeeded_event()
        assert msg.status == MessageStatus.TRANSFORMED
        assert len(msg.trace_events) == trace_count_before
        stateless_ok_events = msg.pull_domain_events()
        assert len(stateless_ok_events) == 1
        assert isinstance(stateless_ok_events[0], DeliverySuccessful)

        msg.record_delivery_failed_event(
            failure_reason="Webhook timeout",
            error_code="HTTP_504",
        )
        assert msg.status == MessageStatus.TRANSFORMED
        assert len(msg.trace_events) == trace_count_before
        stateless_fail_events = msg.pull_domain_events()
        assert len(stateless_fail_events) == 1
        assert isinstance(stateless_fail_events[0], DeliveryFailed)

        msg.fail_transformation(reason="Invalid ISA segment", error_code="ERR_ISA")
        assert msg.status == MessageStatus.FAILED
        tx_fail_events = msg.pull_domain_events()
        assert len(tx_fail_events) == 1
        assert isinstance(tx_fail_events[0], TransformFailed)

        msg.request_delivery(idempotency_key=idem_del)
        del_req_events = msg.pull_domain_events()
        assert len(del_req_events) == 1
        assert isinstance(del_req_events[0], DeliverRequestedEvent)

        msg.complete_delivery()
        assert msg.status == MessageStatus.DELIVERED
        del_ok_events = msg.pull_domain_events()
        assert len(del_ok_events) == 1
        assert isinstance(del_ok_events[0], DeliverySuccessful)

        msg.fail_delivery(reason="AS2 endpoint unreachable", error_code="AS2_DOWN")
        assert msg.status == MessageStatus.FAILED
        del_fail_events = msg.pull_domain_events()
        assert len(del_fail_events) == 1
        assert isinstance(del_fail_events[0], DeliveryFailed)
