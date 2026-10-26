"""Built-in IP Stitch StepHandlerPort adapters for L2 Replica queries and Stage-1 Notifications."""

from __future__ import annotations

from typing import Protocol

from ip.engine.domain.models.replica_record import ReplicaRecord
from ip.engine.domain.stitch import (
    EmitNotificationStepInput,
    EmitNotificationStepOutput,
    QueryReplicaStepInput,
    QueryReplicaStepOutput,
    StitchStepType,
)
from notification.facade import notify
from orchestration.domain.constants import EffectPolicy, StepFailureCode
from orchestration.domain.exceptions import Result
from orchestration.domain.failures import StepFailure, TerminalFailure
from orchestration.ports.inbound.step_handler_port import StepContext, StepHandlerPort
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope


class ReplicaLookupPort(Protocol):
    """Interface-segregated port for querying an L2 ReplicaRecord by stream and record key."""

    async def get_by_key(
        self,
        tenant_id: str,
        connection_id: str,
        stream: str,
        record_key: str,
    ) -> ReplicaRecord | None: ...


class NotificationOutboxPort(Protocol):
    """Port for persisting Stage-1 `notification.requested` EventEnvelopes into the local outbox."""

    async def publish_envelope(self, envelope: EventEnvelope) -> None: ...


class QueryReplicaStepHandler(StepHandlerPort[JsonDict, JsonDict]):
    """Queries an L2 ReplicaRecord inside a Stitch workflow step (`EffectPolicy.PURE`)."""

    def __init__(
        self,
        replica_lookup: ReplicaLookupPort,
    ) -> None:
        self._replica_lookup = replica_lookup

    @property
    def step_type(self) -> str:
        return StitchStepType.QUERY_REPLICA.value

    @property
    def effect_policy(self) -> EffectPolicy:
        return EffectPolicy.PURE

    async def execute(
        self, context: StepContext, step_input: JsonDict
    ) -> Result[JsonDict, StepFailure]:
        parsed_res = QueryReplicaStepInput.from_payload(step_input)
        if parsed_res.is_err:
            return Result.err(
                TerminalFailure(
                    code=StepFailureCode.VALIDATION_REJECTED,
                    detail=parsed_res.unwrap_err().message,
                )
            )
        req = parsed_res.unwrap()

        rec = await self._replica_lookup.get_by_key(
            tenant_id=context.tenant_id,
            connection_id=req.connection_id,
            stream=req.stream,
            record_key=req.record_key,
        )
        if rec is None:
            return Result.ok(QueryReplicaStepOutput(found=False).to_payload())

        return Result.ok(
            QueryReplicaStepOutput(
                found=True,
                record_id=rec.id,
                version=rec.version,
                data=rec.data,
            ).to_payload()
        )


class EmitNotificationStepHandler(StepHandlerPort[JsonDict, JsonDict]):
    """Stage-1 Notification ingestion step handler (`EffectPolicy.IDEMPOTENT_EFFECT`).

    Drops a raw `EventEnvelope(event_type='notification.requested')` into the local outbox
    using `context.idempotency_key` in strict compliance with the 3-Stage Notification Pipeline.
    """

    def __init__(self, outbox: NotificationOutboxPort) -> None:
        self._outbox = outbox

    @property
    def step_type(self) -> str:
        return StitchStepType.EMIT_NOTIFICATION.value

    @property
    def effect_policy(self) -> EffectPolicy:
        return EffectPolicy.IDEMPOTENT_EFFECT

    async def execute(
        self, context: StepContext, step_input: JsonDict
    ) -> Result[JsonDict, StepFailure]:
        parsed_res = EmitNotificationStepInput.from_payload(step_input)
        if parsed_res.is_err:
            return Result.err(
                TerminalFailure(
                    code=StepFailureCode.VALIDATION_REJECTED,
                    detail=parsed_res.unwrap_err().message,
                )
            )
        req = parsed_res.unwrap()

        envelope = notify(
            tenant_id=context.tenant_id,
            source=StitchStepType.EMIT_NOTIFICATION.value,
            notification_type=req.template_id,
            notification_data={
                "channel": req.channel,
                "template_id": req.template_id,
                "recipient": req.recipient,
                "variables": req.variables,
                "run_id": context.run_id,
                "step_run_id": context.step_run_id,
                "trace_id": context.trace_id,
            },
            idempotency_key=context.idempotency_key,
        )
        await self._outbox.publish_envelope(envelope)

        return Result.ok(
            EmitNotificationStepOutput(
                envelope_id=envelope.id,
                event_type=envelope.event_type,
            ).to_payload()
        )


__all__ = [
    "EmitNotificationStepHandler",
    "NotificationOutboxPort",
    "QueryReplicaStepHandler",
    "ReplicaLookupPort",
]
