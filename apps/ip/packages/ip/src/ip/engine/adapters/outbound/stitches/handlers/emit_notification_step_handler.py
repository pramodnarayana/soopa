"""EmitNotificationStepHandler adapter staging Stage-1 notification envelopes."""

from __future__ import annotations

from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.steps.notification_steps import (
    EmitNotificationStepInput,
    EmitNotificationStepOutput,
)
from ip.engine.ports.outbound.notification_outbox_port import NotificationOutboxPort
from notification.facade import notify
from orchestration.domain.constants import EffectPolicy, StepFailureCode
from orchestration.domain.exceptions import Result
from orchestration.domain.failures import StepFailure, TerminalFailure
from orchestration.ports.inbound.step_handler_port import StepContext, StepHandlerPort
from seedwork.domain.types import JsonDict


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
                "event_id": context.idempotency_key,
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


__all__ = ["EmitNotificationStepHandler"]
