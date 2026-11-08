"""Built-in IP Stitch StepHandlerPort adapters for L2 Replica queries, Stage-1 Notifications, and L4->L5 Egress Staging."""

from __future__ import annotations

from typing import Protocol

from ip.engine.application.use_cases.delivery.stage_outbound_delivery_use_case import (
    StageOutboundDeliveryCommand,
    StageOutboundDeliveryResponse,
)
from ip.engine.domain.dispatch.enums import FailureDisposition
from ip.engine.domain.dispatch.outbound_record import OutboundRecord
from ip.engine.domain.exceptions import IpError
from ip.engine.domain.exceptions import Result as IpResult
from ip.engine.domain.replication.replica_record import ReplicaRecord
from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.stitch import (
    EmitNotificationStepInput,
    EmitNotificationStepOutput,
    ExecuteHttpActionStepInput,
    ExecuteHttpActionStepOutput,
    QueryReplicaStepInput,
    QueryReplicaStepOutput,
)
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort
from notification.facade import notify
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
    StepHandlerPort,
)
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


class OutboundDeliveryStagerPort(Protocol):
    """Interface-segregated port for staging an L5 OutboundRecord(PENDING) onto the Egress Queue."""

    async def execute(
        self,
        command: StageOutboundDeliveryCommand,
    ) -> IpResult[StageOutboundDeliveryResponse, IpError]: ...


class OutboundRecordLookupPort(Protocol):
    """Interface-segregated port for looking up an L5 OutboundRecord by idempotency key."""

    async def get_by_idempotency_key(
        self,
        tenant_id: str,
        connection_id: str,
        idempotency_key: str,
    ) -> OutboundRecord | None: ...


class TenantAwareOutboundRecordLookupAdapter(OutboundRecordLookupPort):
    """Adapter fulfilling OutboundRecordLookupPort by routing to the tenant shard via IpDataPlaneUnitOfWorkProviderPort."""

    def __init__(self, uow_provider: IpDataPlaneUnitOfWorkProviderPort) -> None:
        self._provider = uow_provider

    async def get_by_idempotency_key(
        self,
        tenant_id: str,
        connection_id: str,
        idempotency_key: str,
    ) -> OutboundRecord | None:
        shard_info_res = await self._provider.resolve_shard_info(tenant_id)
        if shard_info_res.is_err:
            return None
        shard_id, shard_dsn = shard_info_res.unwrap()
        async with self._provider.get_data_plane_uow(tenant_id, shard_id, shard_dsn) as uow:
            return await uow.outbound_records.get_by_idempotency_key(
                tenant_id=tenant_id,
                connection_id=connection_id,
                idempotency_key=idempotency_key,
            )


class TenantAwareReplicaLookupAdapter(ReplicaLookupPort):
    """Adapter fulfilling ReplicaLookupPort by querying the tenant shard via IpDataPlaneUnitOfWorkProviderPort."""

    def __init__(self, uow_provider: IpDataPlaneUnitOfWorkProviderPort) -> None:
        self._provider = uow_provider

    async def get_by_key(
        self,
        tenant_id: str,
        connection_id: str,
        stream: str,
        record_key: str,
    ) -> ReplicaRecord | None:
        shard_info_res = await self._provider.resolve_shard_info(tenant_id)
        if shard_info_res.is_err:
            raise RuntimeError(
                f"Cannot resolve physical shard for tenant '{tenant_id}': {shard_info_res.unwrap_err().message}"
            )
        shard_id, shard_dsn = shard_info_res.unwrap()
        async with self._provider.get_data_plane_uow(tenant_id, shard_id, shard_dsn) as uow:
            return await uow.replica_records.get_by_key(
                tenant_id=tenant_id,
                connection_id=connection_id,
                stream=stream,
                record_key=record_key,
            )


class TenantAwareNotificationOutboxAdapter(NotificationOutboxPort):
    """Adapter fulfilling NotificationOutboxPort by staging Stage-1 notification envelopes to the tenant shard outbox."""

    def __init__(self, uow_provider: IpDataPlaneUnitOfWorkProviderPort) -> None:
        self._provider = uow_provider

    async def publish_envelope(self, envelope: EventEnvelope) -> None:
        tenant_id = envelope.tenant_id
        if not tenant_id:
            raise ValueError("Cannot stage notification envelope without tenant_id.")
        shard_info_res = await self._provider.resolve_shard_info(tenant_id)
        if shard_info_res.is_err:
            raise RuntimeError(
                f"Cannot resolve physical shard for tenant '{tenant_id}': {shard_info_res.unwrap_err().message}"
            )
        shard_id, shard_dsn = shard_info_res.unwrap()
        async with self._provider.get_data_plane_uow(tenant_id, shard_id, shard_dsn) as uow:
            await uow.stage_outbox_envelope(envelope)
            await uow.commit()


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
    ) -> None:
        self._delivery_stager = delivery_stager
        self._outbound_lookup = outbound_lookup

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

        staged_res = await self._delivery_stager.execute(
            StageOutboundDeliveryCommand(
                tenant_id=context.tenant_id,
                connection_id=req.connection_id,
                stream_name=req.stream_name,
                operation=req.operation,
                payload=req.payload,
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


__all__ = [
    "EmitNotificationStepHandler",
    "ExecuteHttpActionStepHandler",
    "NotificationOutboxPort",
    "OutboundDeliveryStagerPort",
    "OutboundRecordLookupPort",
    "QueryReplicaStepHandler",
    "ReplicaLookupPort",
    "TenantAwareNotificationOutboxAdapter",
    "TenantAwareOutboundRecordLookupAdapter",
    "TenantAwareReplicaLookupAdapter",
]
