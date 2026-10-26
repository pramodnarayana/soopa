"""Domain models, subscriptions, and step DTOs for the IP Layer-4 Stitch Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from orchestration.domain.constants import WorkflowErrorCode
from orchestration.domain.exceptions import Result, WorkflowError
from seedwork.domain.types import JsonDict


class StitchStepType(StrEnum):
    """Enterprise constant step_type identifiers for built-in IP Stitch handlers."""

    QUERY_REPLICA = "ip.stitch.query_replica"
    EXECUTE_HTTP_ACTION = "ip.stitch.execute_http_action"
    EMIT_NOTIFICATION = "ip.stitch.emit_notification"


@dataclass(frozen=True, kw_only=True)
class StitchSubscription:
    """Binds an L3 Canonical Event either to trigger a new Stitch WorkflowRun (`is_trigger=True`)
    or to signal an active `WAIT_FOR_EVENT` condition (`is_trigger=False`).
    """

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
    is_active: bool = True

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


__all__ = [
    "EmitNotificationStepInput",
    "EmitNotificationStepOutput",
    "QueryReplicaStepInput",
    "QueryReplicaStepOutput",
    "StitchStepType",
    "StitchSubscription",
]
