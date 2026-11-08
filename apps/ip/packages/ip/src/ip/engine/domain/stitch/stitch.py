"""Domain models and step DTOs for the IP Layer-4 Stitch Engine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import ClassVar

from orchestration.domain.constants import WorkflowErrorCode
from orchestration.domain.exceptions import Result, WorkflowError
from seedwork.domain.aggregate import AggregateRoot
from seedwork.domain.types import JsonDict, JsonPrimitive

from ip.engine.domain.dispatch.enums import (
    HttpWriteOperation,
    OutboundConflictStrategy,
)
from ip.engine.domain.enums import IpIdPrefix
from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.events import StitchRegisteredEvent


@dataclass(kw_only=True)
class Stitch(AggregateRoot):
    """Connects an L3 Canonical Event to a Stitch Workflow (`is_trigger=True`)
    or signals an active `WAIT_FOR_EVENT` condition (`is_trigger=False`).
    """

    ID_PREFIX: ClassVar[str] = IpIdPrefix.STITCH.value

    id: str
    tenant_id: str
    workflow_id: str
    workflow_version: int
    canonical_event_type: str
    is_trigger: bool = True
    condition_event_key: str | None = None
    idempotency_key_field: str = "id"
    concurrency_key_field: str | None = None
    resource_hint_field: str | None = None
    filter_conditions: Mapping[str, JsonPrimitive] = field(default_factory=dict)
    is_active: bool = True

    def matches_payload(self, payload: JsonDict) -> bool:
        """Evaluates declarative equality predicates against the canonical event payload."""
        if not self.filter_conditions:
            return True
        return all(payload.get(key) == expected for key, expected in self.filter_conditions.items())

    def record_registered(self) -> None:
        """Records a StitchRegisteredEvent domain event on this aggregate."""
        self.add_domain_event(
            StitchRegisteredEvent(
                stitch_id=self.id,
                tenant_id=self.tenant_id,
                workflow_id=self.workflow_id,
                workflow_version=self.workflow_version,
                canonical_event_type=self.canonical_event_type,
                is_trigger=self.is_trigger,
                is_active=self.is_active,
            )
        )

    def extract_idempotency_key(self, payload: JsonDict, fallback_event_id: str) -> str:
        raw_val = payload.get(self.idempotency_key_field)
        if isinstance(raw_val, (str, int)) and str(raw_val).strip():
            return f"{self.workflow_id}:{raw_val}"
        return f"{self.workflow_id}:{fallback_event_id}"

    def extract_concurrency_key(self, payload: JsonDict) -> str | None:
        if self.concurrency_key_field is None:
            return None
        raw_val = payload.get(self.concurrency_key_field)
        if isinstance(raw_val, (str, int)) and str(raw_val).strip():
            return str(raw_val)
        return None

    def extract_resource_hint(self, payload: JsonDict) -> str | None:
        if self.resource_hint_field is None:
            return None
        raw_val = payload.get(self.resource_hint_field)
        if isinstance(raw_val, (str, int)) and str(raw_val).strip():
            return str(raw_val)
        return None


@dataclass(frozen=True, kw_only=True)
class QueryReplicaStepInput:
    """Strongly-typed input DTO for querying an L2 ReplicaRecord inside a Stitch step."""

    connection_id: str
    stream: str
    record_key: str

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[QueryReplicaStepInput, WorkflowError]:
        conn_id = data.get("connection_id")
        stream = data.get("stream")
        rec_key = data.get("record_key")
        if (
            not isinstance(conn_id, str)
            or not conn_id.strip()
            or not isinstance(stream, str)
            or not stream.strip()
            or not isinstance(rec_key, str)
            or not rec_key.strip()
        ):
            return Result.err(
                WorkflowError(
                    code=WorkflowErrorCode.CODEC_ERROR,
                    message="QueryReplicaStepInput requires non-empty string connection_id, stream, and record_key.",
                )
            )
        return Result.ok(
            cls(
                connection_id=conn_id,
                stream=stream,
                record_key=rec_key,
            )
        )


@dataclass(frozen=True, kw_only=True)
class QueryReplicaStepOutput:
    """Strongly-typed output DTO from querying an L2 ReplicaRecord."""

    found: bool
    record_id: str | None = None
    version: int | None = None
    data: JsonDict = field(default_factory=dict)

    def to_payload(self) -> JsonDict:
        return {
            "found": self.found,
            "record_id": self.record_id,
            "version": self.version,
            "data": dict(self.data),
        }


@dataclass(frozen=True, kw_only=True)
class EmitNotificationStepInput:
    """Strongly-typed input DTO for Stage-1 notification ingestion (`notification.requested`)."""

    channel: str
    template_id: str
    recipient: str
    variables: JsonDict = field(default_factory=dict)

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[EmitNotificationStepInput, WorkflowError]:
        channel = data.get("channel")
        template_id = data.get("template_id")
        recipient = data.get("recipient")
        raw_vars = data.get("variables")
        if (
            not isinstance(channel, str)
            or not channel.strip()
            or not isinstance(template_id, str)
            or not template_id.strip()
            or not isinstance(recipient, str)
            or not recipient.strip()
        ):
            return Result.err(
                WorkflowError(
                    code=WorkflowErrorCode.CODEC_ERROR,
                    message="EmitNotificationStepInput requires non-empty channel, template_id, and recipient.",
                )
            )
        variables: JsonDict = dict(raw_vars) if isinstance(raw_vars, dict) else {}
        return Result.ok(
            cls(
                channel=channel,
                template_id=template_id,
                recipient=recipient,
                variables=variables,
            )
        )


@dataclass(frozen=True, kw_only=True)
class EmitNotificationStepOutput:
    """Strongly-typed output DTO after queueing a Stage-1 notification event."""

    envelope_id: str
    event_type: str

    def to_payload(self) -> JsonDict:
        return {
            "envelope_id": self.envelope_id,
            "event_type": self.event_type,
        }


@dataclass(frozen=True, kw_only=True)
class ExecuteHttpActionStepInput:
    """Strongly-typed input DTO for dispatching an L5 outbound mutation from a Stitch step."""

    connection_id: str
    stream_name: str
    operation: str = HttpWriteOperation.CREATE.value
    payload: JsonDict = field(default_factory=dict)
    record_id: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    conflict_strategy: OutboundConflictStrategy = OutboundConflictStrategy.FAIL
    causation_depth: int = 0

    @classmethod
    def from_payload(cls, data: JsonDict) -> Result[ExecuteHttpActionStepInput, WorkflowError]:
        conn_id = data.get("connection_id")
        stream_name = data.get("stream_name") or data.get("stream")
        raw_op = data.get("operation", HttpWriteOperation.CREATE.value)
        raw_payload = data.get("payload")
        raw_record_id = data.get("record_id")
        raw_headers = data.get("headers")
        raw_conflict = data.get("conflict_strategy", OutboundConflictStrategy.FAIL.value)
        raw_causation_depth = data.get("causation_depth", 0)

        if (
            not isinstance(conn_id, str)
            or not conn_id.strip()
            or not isinstance(stream_name, str)
            or not stream_name.strip()
            or not isinstance(raw_op, str)
            or not raw_op.strip()
        ):
            return Result.err(
                WorkflowError(
                    code=WorkflowErrorCode.CODEC_ERROR,
                    message=(
                        "ExecuteHttpActionStepInput requires non-empty connection_id, "
                        "stream_name, and operation."
                    ),
                )
            )

        op_str = raw_op.strip().upper()
        try:
            validated_op = HttpWriteOperation(op_str)
        except ValueError:
            return Result.err(
                WorkflowError(
                    code=WorkflowErrorCode.CODEC_ERROR,
                    message=f"Unsupported HTTP write operation '{raw_op}' for ExecuteHttpActionStepInput",
                )
            )

        payload_dict: JsonDict = dict(raw_payload) if isinstance(raw_payload, dict) else {}
        headers_dict: dict[str, str] = (
            {str(k): str(v) for k, v in raw_headers.items()}
            if isinstance(raw_headers, dict)
            else {}
        )
        try:
            conflict_strat = OutboundConflictStrategy(str(raw_conflict))
        except ValueError:
            conflict_strat = OutboundConflictStrategy.FAIL

        return Result.ok(
            cls(
                connection_id=conn_id.strip(),
                stream_name=stream_name.strip(),
                operation=validated_op.value,
                payload=payload_dict,
                record_id=str(raw_record_id).strip()
                if isinstance(raw_record_id, (str, int)) and str(raw_record_id).strip()
                else None,
                headers=headers_dict,
                conflict_strategy=conflict_strat,
                causation_depth=(
                    raw_causation_depth
                    if isinstance(raw_causation_depth, int)
                    and not isinstance(raw_causation_depth, bool)
                    else 0
                ),
            )
        )


@dataclass(frozen=True, kw_only=True)
class ExecuteHttpActionStepOutput:
    """Strongly-typed output DTO returned after an L5 outbound dispatch completes."""

    outbound_record_id: str
    status: str
    record_id: str
    destination_id: str | None = None
    response_status_code: int | None = None
    response_body: JsonDict | None = None
    response_s3_key: str | None = None
    was_deduplicated: bool = False
    was_token_refreshed: bool = False

    def to_payload(self) -> JsonDict:
        return {
            "outbound_record_id": self.outbound_record_id,
            "status": self.status,
            "record_id": self.record_id,
            "destination_id": self.destination_id,
            "response_status_code": self.response_status_code,
            "response_body": dict(self.response_body) if self.response_body is not None else None,
            "response_s3_key": self.response_s3_key,
            "was_deduplicated": self.was_deduplicated,
            "was_token_refreshed": self.was_token_refreshed,
        }


__all__ = [
    "EmitNotificationStepInput",
    "EmitNotificationStepOutput",
    "ExecuteHttpActionStepInput",
    "ExecuteHttpActionStepOutput",
    "QueryReplicaStepInput",
    "QueryReplicaStepOutput",
    "Stitch",
    "StitchStepType",
]
