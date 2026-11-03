"""Base Traced Aggregate Root for EDI Data-Plane Records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from seedwork.domain.types import JsonDict
from seedwork.utils import generate_id
from strace.domain import TracedAggregateRoot, TraceEvent

from edi.domain.constants import EdiIdPrefix as DomainIdPrefix
from edi.domain.enums import EdiTraceEventType
from edi.domain.routing.enums import EdiDirection
from edi.domain.transaction.enums import MessageStatus
from edi.domain.transaction.events import (
    DeliverRequestedEvent,
    DeliveryFailed,
    DeliverySuccessful,
    TransformFailed,
    TransformRequestedEvent,
    TransformSuccessful,
)

__all__ = ["EdiRecordBase"]


@dataclass(kw_only=True)
class EdiRecordBase(TracedAggregateRoot):
    id: str
    direction: EdiDirection
    status: MessageStatus
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    status_message: str | None = None
    error_code: str | None = None
    error_details: JsonDict | None = None

    def __post_init__(self) -> None:
        if isinstance(self.id, UUID):
            self.id = str(self.id)
        if isinstance(self.tenant_id, UUID):
            self.tenant_id = str(self.tenant_id)
        if isinstance(self.trace_id, UUID):
            self.trace_id = str(self.trace_id)

    def _append_trace(
        self, event_type: str, *, actor: str = "SYSTEM", **metadata: str | None
    ) -> None:
        """Internal helper to append a rich trace event to the ledger."""
        self.add_trace_event(
            TraceEvent(
                id=generate_id(DomainIdPrefix.EDI_TRACE_EVENT.value),
                tenant_id=self.tenant_id,
                trace_id=self.trace_id,
                event_type=event_type,
                actor=actor,
                metadata={k: v for k, v in metadata.items() if v is not None},
            )
        )

    def mark_delivery_attempt_failed(
        self,
        reason: str,
        error_code: str | None = None,
        error_details: JsonDict | None = None,
        stack_trace: str | None = None,
    ) -> None:
        self.status_message = reason[:255]
        self.error_code = error_code
        self.error_details = error_details
        self._append_trace(
            EdiTraceEventType.DELIVERY_ATTEMPT_FAILED,
            reason=reason,
            error_code=error_code,
            stack_trace=stack_trace,
        )

    def mark_delivery_failed(
        self,
        reason: str,
        error_code: str | None = None,
        error_details: JsonDict | None = None,
        stack_trace: str | None = None,
    ) -> None:
        self.status = MessageStatus.FAILED

        if self.status_message and reason == "Max delivery retries exceeded.":
            self.status_message = f"{self.status_message} (Max retries exceeded)"[:255]
        else:
            self.status_message = reason[:255]
            if error_code:
                self.error_code = error_code
            if error_details:
                self.error_details = error_details

        self._append_trace(
            EdiTraceEventType.DELIVERY_FAILED,
            reason=self.status_message,
            error_code=self.error_code,
            stack_trace=stack_trace,
        )

    def mark_transform_failed(
        self,
        reason: str,
        error_code: str | None = None,
        error_details: JsonDict | None = None,
        stack_trace: str | None = None,
    ) -> None:
        self.status = MessageStatus.FAILED
        self.status_message = reason[:255]
        if error_code:
            self.error_code = error_code
        if error_details:
            self.error_details = error_details
        self._append_trace(
            EdiTraceEventType.TRANSFORMATION_FAILED,
            reason=self.status_message,
            error_code=self.error_code,
            stack_trace=stack_trace,
        )

    def mark_delivered(self) -> None:
        self.status = MessageStatus.DELIVERED
        self.status_message = None
        self.error_code = None
        self.error_details = None
        self._append_trace(EdiTraceEventType.DELIVERY_SUCCESSFUL)

    def mark_transformed(self) -> None:
        self.status = MessageStatus.TRANSFORMED
        self.status_message = None
        self.error_code = None
        self.error_details = None
        self._append_trace(EdiTraceEventType.TRANSFORMATION_SUCCESSFUL)

    def mark_replay_triggered(self, actor: str) -> None:
        self._append_trace(EdiTraceEventType.REPLAY_TRIGGERED, actor=actor)

    def record_modified_and_replayed(
        self,
        *,
        new_trace_id: str,
        event_type: EdiTraceEventType,
        actor: str,
    ) -> None:
        """Record an audit trace event on the original stage record when modified and replayed."""
        self._append_trace(event_type.value, actor=actor, new_trace_id=new_trace_id)

    def record_created_from_modification(
        self,
        *,
        parent_trace_id: str,
        original_trace_id: str,
        actor: str,
    ) -> None:
        """Record an audit trace event on a newly cloned stage record created via modification."""
        self._append_trace(
            EdiTraceEventType.CREATED_FROM_MODIFICATION.value,
            actor=actor,
            parent_trace_id=parent_trace_id,
            original_trace_id=original_trace_id,
        )

    def record_bulk_replay_transform(self, *, actor: str) -> None:
        """Record a bulk transform replay audit trace event on this aggregate."""
        self._append_trace(
            EdiTraceEventType.REPLAY_TRANSFORM.value,
            actor=actor,
            replay_type="transform",
        )

    def record_bulk_replay_deliver(self, *, actor: str) -> None:
        """Record a bulk delivery replay audit trace event on this aggregate."""
        self._append_trace(
            EdiTraceEventType.REPLAY_DELIVER.value,
            actor=actor,
            replay_type="deliver",
        )

    def record_received(self, *, actor: str = "SYSTEM", **metadata: str | None) -> None:
        """Record the initial RECEIVED trace event on this transaction aggregate."""
        self._append_trace(EdiTraceEventType.RECEIVED, actor=actor, **metadata)

    def request_transformation(
        self,
        *,
        trading_partner_id: str | None = None,
        sender_id: str | None = None,
        receiver_id: str | None = None,
        edi_message_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        """Enqueue a TransformRequestedEvent domain event on this aggregate."""
        event_kwargs: dict[str, str | None] = {
            "trace_id": str(self.trace_id),
            "tenant_id": str(self.tenant_id),
            "trading_partner_id": trading_partner_id,
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "direction": str(self.direction.value) if self.direction else None,
            "edi_message_id": edi_message_id,
        }
        if idempotency_key is not None:
            self.add_domain_event(
                TransformRequestedEvent(
                    trace_id=str(self.trace_id),
                    tenant_id=str(self.tenant_id),
                    trading_partner_id=trading_partner_id,
                    sender_id=sender_id,
                    receiver_id=receiver_id,
                    direction=event_kwargs["direction"],
                    edi_message_id=edi_message_id,
                    idempotency_key=idempotency_key,
                )
            )
        else:
            self.add_domain_event(
                TransformRequestedEvent(
                    trace_id=str(self.trace_id),
                    tenant_id=str(self.tenant_id),
                    trading_partner_id=trading_partner_id,
                    sender_id=sender_id,
                    receiver_id=receiver_id,
                    direction=event_kwargs["direction"],
                    edi_message_id=edi_message_id,
                )
            )

    def request_delivery(
        self,
        *,
        trading_partner_id: str | None = None,
        transaction_type: str | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        """Enqueue a DeliverRequestedEvent domain event on this aggregate."""
        direction_val = str(self.direction.value) if self.direction else None
        if idempotency_key is not None:
            self.add_domain_event(
                DeliverRequestedEvent(
                    trace_id=str(self.trace_id),
                    tenant_id=str(self.tenant_id),
                    trading_partner_id=trading_partner_id,
                    transaction_type=transaction_type,
                    direction=direction_val,
                    idempotency_key=idempotency_key,
                )
            )
        else:
            self.add_domain_event(
                DeliverRequestedEvent(
                    trace_id=str(self.trace_id),
                    tenant_id=str(self.tenant_id),
                    trading_partner_id=trading_partner_id,
                    transaction_type=transaction_type,
                    direction=direction_val,
                )
            )

    def complete_transformation(
        self,
        *,
        direction: str | None = None,
        isa_sender_id: str | None = None,
        isa_receiver_id: str | None = None,
        gs_sender_id: str | None = None,
        gs_receiver_id: str | None = None,
        transaction_type: str | None = None,
    ) -> None:
        """Mark transformation complete, record audit trace, and emit TransformSuccessful."""
        self.mark_transformed()
        self.add_domain_event(
            TransformSuccessful(
                trace_id=str(self.trace_id),
                tenant_id=str(self.tenant_id or ""),
                direction=direction or (str(self.direction.value) if self.direction else ""),
                isa_sender_id=isa_sender_id,
                isa_receiver_id=isa_receiver_id,
                gs_sender_id=gs_sender_id,
                gs_receiver_id=gs_receiver_id,
                transaction_type=transaction_type,
            )
        )

    def fail_transformation(
        self,
        *,
        reason: str,
        error_code: str | None = None,
        error_details: JsonDict | None = None,
        direction: str | None = None,
        tenant_id: str | None = None,
        stack_trace: str | None = None,
    ) -> None:
        """Mark transformation failed, record audit trace, and emit TransformFailed."""
        self.mark_transform_failed(
            reason=reason,
            error_code=error_code,
            error_details=error_details,
            stack_trace=stack_trace,
        )
        self.add_domain_event(
            TransformFailed(
                trace_id=str(self.trace_id),
                tenant_id=tenant_id or str(self.tenant_id or ""),
                direction=direction or (str(self.direction.value) if self.direction else ""),
                failure_reason=reason,
                error_code=error_code,
                error_details=error_details,
            )
        )

    def record_delivery_succeeded_event(
        self,
        *,
        trace_id: str | None = None,
        tenant_id: str | None = None,
        direction: str | None = None,
    ) -> None:
        """Emit DeliverySuccessful without mutating this aggregate's status."""
        self.add_domain_event(
            DeliverySuccessful(
                trace_id=trace_id or str(self.trace_id),
                tenant_id=tenant_id or str(self.tenant_id),
                direction=direction
                or (str(self.direction.value) if self.direction else EdiDirection.OUTBOUND.value),
            )
        )

    def complete_delivery(
        self,
        *,
        trace_id: str | None = None,
        tenant_id: str | None = None,
        direction: str | None = None,
    ) -> None:
        """Mark delivery succeeded, record audit trace, and emit DeliverySuccessful."""
        self.mark_delivered()
        self.record_delivery_succeeded_event(
            trace_id=trace_id,
            tenant_id=tenant_id,
            direction=direction,
        )

    def record_delivery_failed_event(
        self,
        *,
        failure_reason: str,
        error_code: str | None = None,
        error_details: JsonDict | None = None,
        trace_id: str | None = None,
        tenant_id: str | None = None,
        direction: str | None = None,
    ) -> None:
        """Emit DeliveryFailed without mutating this aggregate's status."""
        self.add_domain_event(
            DeliveryFailed(
                trace_id=trace_id or str(self.trace_id),
                tenant_id=tenant_id or str(self.tenant_id),
                direction=direction
                or (str(self.direction.value) if self.direction else EdiDirection.OUTBOUND.value),
                failure_reason=failure_reason,
                error_code=error_code if error_code is not None else self.error_code,
                error_details=error_details if error_details is not None else self.error_details,
            )
        )

    def fail_delivery(
        self,
        *,
        reason: str,
        failure_reason: str | None = None,
        error_code: str | None = None,
        error_details: JsonDict | None = None,
        trace_id: str | None = None,
        tenant_id: str | None = None,
        direction: str | None = None,
        stack_trace: str | None = None,
    ) -> None:
        """Mark delivery failed, record audit trace, and emit DeliveryFailed."""
        self.mark_delivery_failed(
            reason=reason,
            error_code=error_code,
            error_details=error_details,
            stack_trace=stack_trace,
        )
        self.record_delivery_failed_event(
            failure_reason=failure_reason or reason,
            error_code=error_code,
            error_details=error_details,
            trace_id=trace_id,
            tenant_id=tenant_id,
            direction=direction,
        )
