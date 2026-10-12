from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from seedwork.domain.types import JsonDict
from seedwork.id_registry import DomainIdPrefix
from seedwork.models import TracedAggregateRoot, TraceEvent
from seedwork.utils import generate_id

from edi.domain.enums import EdiDirection, MessageStatus, TraceEventType

# Re-export canonical enums so existing callers of `from edi.domain.models.base import ...`
# keep working without changes during the transition.
Direction = EdiDirection
RecordStatus = MessageStatus


class PartnerStatus(StrEnum):
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ConnectionType(StrEnum):
    AS2 = "AS2"
    SFTP = "SFTP"
    WEBHOOK = "WEBHOOK"
    API = "API"


class ProcessingMode(StrEnum):
    TRANSFORM = "TRANSFORM"
    PASSTHROUGH = "PASSTHROUGH"


@dataclass(kw_only=True)
class EdiRecordBase(TracedAggregateRoot):
    id: str
    tenant_id: str
    trace_id: str
    direction: EdiDirection
    status: MessageStatus
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    replay_count: int = 0
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
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

    def _append_trace(self, event_type: str, actor: str = "SYSTEM", **metadata: str | None) -> None:
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
            TraceEventType.DELIVERY_ATTEMPT_FAILED,
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
            TraceEventType.DELIVERY_FAILED,
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
            TraceEventType.TRANSFORMATION_FAILED,
            reason=self.status_message,
            error_code=self.error_code,
            stack_trace=stack_trace,
        )

    def mark_delivered(self) -> None:
        self.status = MessageStatus.DELIVERED
        self.status_message = None
        self.error_code = None
        self.error_details = None
        self._append_trace(TraceEventType.DELIVERY_SUCCESSFUL)

    def mark_transformed(self) -> None:
        self.status = MessageStatus.TRANSFORMED
        self.status_message = None
        self.error_code = None
        self.error_details = None
        self._append_trace(TraceEventType.TRANSFORMATION_SUCCESSFUL)

    def mark_replay_triggered(self, actor: str) -> None:
        self._append_trace(TraceEventType.REPLAY_TRIGGERED, actor=actor)
