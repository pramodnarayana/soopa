"""ExecuteHttpActionStepHandler reconcilable adapter staging L5 Outbound records."""

from __future__ import annotations

from ip.engine.application.use_cases.delivery.stage_outbound_delivery_use_case import (
    StageOutboundDeliveryCommand,
)
from ip.engine.domain.dispatch.enums import FailureDisposition
from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.steps.http_steps import (
    ExecuteHttpActionStepInput,
    ExecuteHttpActionStepOutput,
)
from ip.engine.ports.outbound.mapping_spec_repository_port import (
    MappingSpecRepositoryPort,
)
from ip.engine.ports.outbound.outbound_delivery_stager_port import (
    OutboundDeliveryStagerPort,
)
from ip.engine.ports.outbound.outbound_record_lookup_port import (
    OutboundRecordLookupPort,
)
from orchestration.domain.constants import EffectPolicy, StepFailureCode
from orchestration.domain.exceptions import Result
from orchestration.domain.failures import (
    ReconcileOutcome,
    RetryableFailure,
    StepFailure,
    TerminalFailure,
)
from orchestration.ports.inbound.step_handler_port import (
    ReconcilableStepHandlerPort,
    StepContext,
)
from seedwork.domain.types import JsonDict


class ExecuteHttpActionStepHandler(ReconcilableStepHandlerPort[JsonDict, JsonDict]):
    """Layer-4 to Layer-5 Reconcilable Stitch Egress Stager (`EffectPolicy.RECONCILABLE_EFFECT`).

    Stages an `OutboundRecord(PENDING)` + `OutboundRecordCreatedEvent` into `public.ip_outbox`
    using `context.idempotency_key` with zero external HTTP calls inside `ip-orchestrator-worker`,
    preserving strict bulkhead isolation between compute orchestration and L5 external I/O.
    """

    def __init__(
        self,
        *,
        delivery_stager: OutboundDeliveryStagerPort,
        outbound_lookup: OutboundRecordLookupPort,
        mapping_spec_repository: MappingSpecRepositoryPort | None = None,
    ) -> None:
        self._delivery_stager = delivery_stager
        self._outbound_lookup = outbound_lookup
        self._mapping_spec_repo = mapping_spec_repository

    @property
    def step_type(self) -> str:
        return StitchStepType.EXECUTE_HTTP_ACTION.value

    @property
    def effect_policy(self) -> EffectPolicy:
        return EffectPolicy.RECONCILABLE_EFFECT

    async def execute(
        self, context: StepContext, step_input: JsonDict
    ) -> Result[JsonDict, StepFailure]:
        parsed_res = ExecuteHttpActionStepInput.from_payload(step_input)
        if parsed_res.is_err:
            return Result.err(
                TerminalFailure(
                    code=StepFailureCode.VALIDATION_REJECTED,
                    detail=parsed_res.unwrap_err().message,
                )
            )
        req = parsed_res.unwrap()

        # Declarative field mapping projection (CIM IEC 61968 -> target wire contract)
        payload_to_deliver = req.payload
        if req.mapping_spec_id and self._mapping_spec_repo is not None:
            spec = await self._mapping_spec_repo.get_by_id(
                tenant_id=context.tenant_id,
                mapping_spec_id=req.mapping_spec_id,
            )
            if spec is None:
                return Result.err(
                    TerminalFailure(
                        code=StepFailureCode.VALIDATION_REJECTED,
                        detail=(
                            f"Referenced mapping_spec_id '{req.mapping_spec_id}' was not found "
                            f"for tenant '{context.tenant_id}'."
                        ),
                    )
                )
            payload_to_deliver = spec.project(req.payload)

        staged_res = await self._delivery_stager.execute(
            StageOutboundDeliveryCommand(
                tenant_id=context.tenant_id,
                connection_id=req.connection_id,
                stream_name=req.stream_name,
                operation=req.operation,
                payload=payload_to_deliver,
                record_id=req.record_id,
                idempotency_key=context.idempotency_key,
                headers=req.headers,
                conflict_strategy=req.conflict_strategy,
                trace_id=context.trace_id,
                correlation_id=context.correlation_id,
                causation_depth=req.causation_depth,
            )
        )
        if staged_res.is_err or staged_res.value is None:
            err = staged_res.error
            detail = err.message if err is not None else "Outbound egress staging failed."
            if err is not None and err.disposition is FailureDisposition.RETRY:
                return Result.err(
                    RetryableFailure(
                        code=StepFailureCode.UPSTREAM_5XX,
                        detail=detail,
                        is_app_error=False,
                    )
                )
            return Result.err(
                TerminalFailure(
                    code=StepFailureCode.VALIDATION_REJECTED,
                    detail=detail,
                )
            )

        outcome = staged_res.value
        return Result.ok(
            ExecuteHttpActionStepOutput(
                outbound_record_id=outcome.outbound_record_id,
                status=outcome.status.value,
                record_id=outcome.record_id,
                was_deduplicated=outcome.was_deduplicated,
            ).to_payload()
        )

    async def reconcile(
        self, context: StepContext, step_input: JsonDict
    ) -> Result[ReconcileOutcome[JsonDict], StepFailure]:
        parsed_res = ExecuteHttpActionStepInput.from_payload(step_input)
        if parsed_res.is_err:
            return Result.err(
                TerminalFailure(
                    code=StepFailureCode.VALIDATION_REJECTED,
                    detail=parsed_res.unwrap_err().message,
                )
            )
        req = parsed_res.unwrap()

        existing = await self._outbound_lookup.get_by_idempotency_key(
            tenant_id=context.tenant_id,
            connection_id=req.connection_id,
            idempotency_key=context.idempotency_key,
        )
        if existing is not None:
            adopted = ExecuteHttpActionStepOutput(
                outbound_record_id=existing.id,
                status=existing.status.value,
                record_id=existing.external_record_id or req.record_id or "",
                destination_id=existing.external_record_id,
                response_status_code=existing.response_status_code,
                response_body=existing.response_body,
                response_s3_key=existing.response_s3_key,
                was_deduplicated=True,
                was_token_refreshed=False,
            ).to_payload()
            return Result.ok(ReconcileOutcome.adopt(adopted))

        return Result.ok(ReconcileOutcome(found=False, adopted_output=None))


__all__ = ["ExecuteHttpActionStepHandler"]
