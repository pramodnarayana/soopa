"""EgressPublishStepHandler publishing mapped records to Kafka or outbox."""

from __future__ import annotations

import structlog
from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.steps.pipeline_stage_steps import (
    EgressPublishStepInput,
    EgressPublishStepOutput,
)
from ip.engine.ports.outbound.notification_outbox_port import NotificationOutboxPort
from orchestration.domain.constants import EffectPolicy, StepFailureCode
from orchestration.domain.exceptions import Result
from orchestration.domain.failures import StepFailure, TerminalFailure
from orchestration.ports.inbound.step_handler_port import StepContext, StepHandlerPort
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope

logger = structlog.get_logger(__name__)


class EgressPublishStepHandler(StepHandlerPort[JsonDict, JsonDict]):
    """Publishes mapped records to the egress Kafka topic or outbox staging queue."""

    def __init__(
        self,
        *,
        notification_outbox: NotificationOutboxPort | None = None,
    ) -> None:
        self._outbox = notification_outbox

    @property
    def step_type(self) -> str:
        return StitchStepType.EGRESS_PUBLISH.value

    @property
    def effect_policy(self) -> EffectPolicy:
        return EffectPolicy.IDEMPOTENT_EFFECT

    async def execute(
        self, context: StepContext, step_input: JsonDict
    ) -> Result[JsonDict, StepFailure]:
        bound = logger.bind(
            tenant_id=context.tenant_id,
            run_id=context.run_id,
            node_key=context.node_key,
        )
        bound.info("egress_publish.received")

        parsed_res = EgressPublishStepInput.from_payload(step_input)
        if parsed_res.is_err:
            detail = parsed_res.unwrap_err().message
            bound.error("egress_publish.validation_failed", detail=detail)
            return Result.err(
                TerminalFailure(code=StepFailureCode.VALIDATION_REJECTED, detail=detail)
            )
        req = parsed_res.unwrap()

        count = len(req.records)
        if self._outbox is not None:
            for idx, rec in enumerate(req.records):
                key_val = str(rec.get(req.destination_partition_key_field, idx))
                envelope = EventEnvelope(
                    id=f"egress_{context.run_id}_{idx}",
                    source=StitchStepType.EGRESS_PUBLISH.value,
                    event_type=req.destination_topic,
                    tenant_id=context.tenant_id,
                    idempotency_key=f"{context.idempotency_key}_{idx}_{key_val}",
                    payload=rec,
                    trace_id=context.trace_id,
                    correlation_id=context.correlation_id,
                )
                await self._outbox.publish_envelope(envelope)

        output = EgressPublishStepOutput(
            published_count=count,
            destination_topic=req.destination_topic,
        )
        bound.info("egress_publish.completed", published_count=count, topic=req.destination_topic)
        return Result.ok(output.to_payload())


__all__ = ["EgressPublishStepHandler"]
