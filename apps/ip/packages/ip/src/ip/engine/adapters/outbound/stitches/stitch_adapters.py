"""Layer-4 Stitch adapters for IP Data Plane."""

from __future__ import annotations

import contextlib
from collections.abc import Callable

import structlog
from database.router import DatabaseRouterPort
from ip.engine.application.use_cases.stitch.dispatch_canonical_event_to_stitches_use_case import (
    DispatchCanonicalEventResultDTO,
    DispatchCanonicalEventToStitchesCommand,
    DispatchCanonicalEventToStitchesUseCase,
)
from ip.engine.application.use_cases.stitch.execute_stitch_worker_tick_use_case import (
    ExecuteStitchWorkerTickCommand,
    ExecuteStitchWorkerTickUseCase,
    StitchWorkerTickResultDTO,
)
from ip.engine.application.worker_ports import (
    IpStitchCanonicalDispatcherPort,
    IpStitchWorkerTickExecutorPort,
)
from ip.engine.domain.exceptions import (
    IpError,
    IpErrorCode,
    StitchRunNotFoundError,
    TenantShardNotFoundError,
)
from ip.engine.ports.outbound.stitch_catalog_registry_port import (
    StitchCatalogRegistryPort,
    StitchShardGatewayPort,
)
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)
from orchestration.application.default_error_policy import DefaultStepErrorPolicy
from orchestration.application.services import WorkflowStepSchedulerService
from orchestration.application.use_cases import (
    ClaimStepsUseCase,
    CompleteStepUseCase,
    FailStepUseCase,
    ResolveMatchConditionsUseCase,
    StartRunUseCase,
)
from orchestration.domain.constants import RunStatus, WorkflowErrorCode
from orchestration.domain.exceptions import Result, WorkflowError
from orchestration.domain.run import WorkflowRun
from orchestration.ports.inbound.step_handler_port import (
    StepHandlerRegistryPort,
    WorkflowDefinitionRegistryPort,
)
from orchestration.ports.outbound import WorkflowUnitOfWorkPort
from seedwork.domain.types import JsonDict
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class IpStitchCanonicalDispatcherAdapter(
    IpStitchCanonicalDispatcherPort, StitchShardGatewayPort
):
    """Routes `DispatchCanonicalEventToStitchesCommand` and run queries to the tenant's IP data plane."""

    def __init__(
        self,
        *,
        db_router: DatabaseRouterPort,
        dp_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        stitch_catalog: StitchCatalogRegistryPort,
        definition_registry: WorkflowDefinitionRegistryPort,
        workflow_uow_factory: Callable[[AsyncSession], WorkflowUnitOfWorkPort],
        control_plane_uow_factory: Callable[[AsyncSession], IpControlPlaneUnitOfWorkPort]
        | None = None,
    ) -> None:
        self._db_router = db_router
        self._dp_uow_provider = dp_uow_provider
        self._stitch_catalog = stitch_catalog
        self._definition_registry = definition_registry
        self._workflow_uow_factory = workflow_uow_factory
        self._control_plane_uow_factory = control_plane_uow_factory
        self._scheduler = WorkflowStepSchedulerService()

    async def get_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
    ) -> Result[WorkflowRun, IpError]:
        shard_res = await self._dp_uow_provider.resolve_shard_info(tenant_id)
        if shard_res.is_err:
            return Result.err(shard_res.unwrap_err())
        shard_id, shard_dsn = shard_res.unwrap()

        async with contextlib.aclosing(
            self._db_router.get_tenant_session(tenant_id, shard_id, shard_dsn)
        ) as session_gen:
            async for session in session_gen:
                uow = self._workflow_uow_factory(session)
                async with uow:
                    run_res = await uow.runs.get_by_id(tenant_id, run_id)
                    if run_res.is_err:
                        return Result.err(StitchRunNotFoundError.for_id(run_id))
                    return Result.ok(run_res.unwrap())

        return Result.err(StitchRunNotFoundError.for_id(run_id))

    async def list_runs(
        self,
        *,
        tenant_id: str,
        workflow_id: str | None = None,
        status: RunStatus | None = None,
        limit: int = 50,
    ) -> Result[tuple[WorkflowRun, ...], IpError]:
        bound = logger.bind(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            status=status.value if status is not None else None,
            limit=limit,
        )
        bound.info("ip_stitch_adapter.list_runs_started")
        shard_res = await self._dp_uow_provider.resolve_shard_info(tenant_id)
        if shard_res.is_err:
            err = shard_res.unwrap_err()
            bound.error(
                "ip_stitch_adapter.shard_resolution_failed",
                error_code=err.code.value,
                message=err.message,
            )
            return Result.err(err)
        shard_id, shard_dsn = shard_res.unwrap()

        async with contextlib.aclosing(
            self._db_router.get_tenant_session(tenant_id, shard_id, shard_dsn)
        ) as session_gen:
            async for session in session_gen:
                uow = self._workflow_uow_factory(session)
                async with uow:
                    runs = await uow.runs.list_recent(
                        tenant_id,
                        workflow_id=workflow_id,
                        status=status,
                        limit=limit,
                    )
                    bound.info(
                        "ip_stitch_adapter.list_runs_completed",
                        shard_id=shard_id,
                        count=len(runs),
                    )
                    return Result.ok(tuple(runs))

        bound.error("ip_stitch_adapter.session_unavailable", shard_id=shard_id)
        return Result.err(TenantShardNotFoundError.for_tenant(tenant_id))

    async def dispatch_event(
        self,
        *,
        tenant_id: str,
        canonical_event_type: str,
        event_id: str,
        payload: JsonDict,
        trace_id: str,
        correlation_id: str | None = None,
    ) -> Result[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]], IpError]:
        shard_res = await self._dp_uow_provider.resolve_shard_info(tenant_id)
        if shard_res.is_err:
            return Result.err(shard_res.unwrap_err())
        res = await self.execute(
            DispatchCanonicalEventToStitchesCommand(
                tenant_id=tenant_id,
                canonical_event_type=canonical_event_type,
                event_id=event_id,
                payload=payload,
                trace_id=trace_id,
                correlation_id=correlation_id,
            )
        )
        if res.is_err:
            wf_err = res.unwrap_err()
            return Result.err(
                IpError(
                    code=IpErrorCode.VALIDATION_FAILED,
                    message=wf_err.message,
                    http_status=400,
                    details=dict(wf_err.details),
                )
            )
        dto = res.unwrap()
        return Result.ok(
            (
                dto.started_run_ids,
                dto.deduplicated_run_ids,
                dto.signalled_step_ids,
            )
        )

    async def execute(
        self, command: DispatchCanonicalEventToStitchesCommand
    ) -> Result[DispatchCanonicalEventResultDTO, WorkflowError]:
        shard_res = await self._dp_uow_provider.resolve_shard_info(command.tenant_id)
        if shard_res.is_err:
            err = shard_res.unwrap_err()
            return Result.err(
                WorkflowError(
                    code=WorkflowErrorCode.RUN_NOT_FOUND,
                    message=err.message,
                    details={"tenant_id": command.tenant_id},
                )
            )
        shard_id, shard_dsn = shard_res.unwrap()

        async with contextlib.aclosing(
            self._db_router.get_tenant_session(
                command.tenant_id, shard_id, shard_dsn
            )
        ) as tenant_gen:
            async for session in tenant_gen:

                def _uow_factory(s: AsyncSession = session) -> WorkflowUnitOfWorkPort:
                    return self._workflow_uow_factory(s)

                match_resolver = ResolveMatchConditionsUseCase(
                    uow_factory=_uow_factory,
                    definition_registry=self._definition_registry,
                    step_scheduler=self._scheduler,
                )
                start_run = StartRunUseCase(
                    uow_factory=_uow_factory,
                    definition_registry=self._definition_registry,
                    step_scheduler=self._scheduler,
                )
                if self._control_plane_uow_factory is not None:
                    async with contextlib.aclosing(
                        self._db_router.get_global_session()
                    ) as global_gen:
                        async for global_session in global_gen:
                            cp_uow = self._control_plane_uow_factory(global_session)
                            use_case = DispatchCanonicalEventToStitchesUseCase(
                                stitch_catalog=self._stitch_catalog,
                                start_run_use_case=start_run,
                                resolve_matches_use_case=match_resolver,
                                control_plane_uow=cp_uow,
                            )
                            return await use_case.execute(command)

                use_case = DispatchCanonicalEventToStitchesUseCase(
                    stitch_catalog=self._stitch_catalog,
                    start_run_use_case=start_run,
                    resolve_matches_use_case=match_resolver,
                )
                return await use_case.execute(command)

        return Result.ok(
            DispatchCanonicalEventResultDTO(
                started_run_ids=(),
                deduplicated_run_ids=(),
                signalled_step_ids=(),
            )
        )


class IpStitchWorkerTickAdapter(IpStitchWorkerTickExecutorPort):
    """Executes `ExecuteStitchWorkerTickUseCase` across all active IP tenant shards."""

    def __init__(
        self,
        *,
        db_router: DatabaseRouterPort,
        definition_registry: WorkflowDefinitionRegistryPort,
        handler_registry: StepHandlerRegistryPort,
        workflow_uow_factory: Callable[[AsyncSession], WorkflowUnitOfWorkPort],
        app_slug: str = "ip",
    ) -> None:
        self._db_router = db_router
        self._definition_registry = definition_registry
        self._handler_registry = handler_registry
        self._workflow_uow_factory = workflow_uow_factory
        self._app_slug = app_slug
        self._scheduler = WorkflowStepSchedulerService()
        self._error_policy = DefaultStepErrorPolicy()

    async def execute(
        self, command: ExecuteStitchWorkerTickCommand
    ) -> Result[StitchWorkerTickResultDTO, WorkflowError]:
        shards = await self._db_router.get_all_shards(app_slug=self._app_slug)
        completed: list[str] = []
        failed: list[str] = []
        parked: list[str] = []
        woken: list[str] = []

        for shard_name, shard_dsn in shards:
            try:
                async with contextlib.aclosing(
                    self._db_router.get_shard_session(shard_name, shard_dsn)
                ) as shard_gen:
                    async for session in shard_gen:

                        def _uow_factory(s: AsyncSession = session) -> WorkflowUnitOfWorkPort:
                            return self._workflow_uow_factory(s)

                        match_resolver = ResolveMatchConditionsUseCase(
                            uow_factory=_uow_factory,
                            definition_registry=self._definition_registry,
                            step_scheduler=self._scheduler,
                        )
                        claim_steps = ClaimStepsUseCase(
                            uow_factory=_uow_factory,
                            definition_registry=self._definition_registry,
                            step_scheduler=self._scheduler,
                            match_resolver=match_resolver,
                        )
                        complete_step = CompleteStepUseCase(
                            uow_factory=_uow_factory,
                            definition_registry=self._definition_registry,
                            step_scheduler=self._scheduler,
                            match_resolver=match_resolver,
                        )
                        fail_step = FailStepUseCase(
                            uow_factory=_uow_factory,
                            definition_registry=self._definition_registry,
                            error_policy=self._error_policy,
                            step_scheduler=self._scheduler,
                            match_resolver=match_resolver,
                        )
                        tick_uc = ExecuteStitchWorkerTickUseCase(
                            claim_steps_use_case=claim_steps,
                            complete_step_use_case=complete_step,
                            fail_step_use_case=fail_step,
                            handler_registry=self._handler_registry,
                        )
                        res = await tick_uc.execute(command)
                        if res.is_err:
                            err = res.unwrap_err()
                            logger.error(
                                "ip_stitch_tick_shard_failed",
                                shard_name=shard_name,
                                error_code=err.code.value,
                                message=err.message,
                            )
                            continue
                        dto = res.unwrap()
                        completed.extend(dto.completed_step_ids)
                        failed.extend(dto.failed_or_retried_step_ids)
                        parked.extend(dto.parked_step_ids)
                        woken.extend(dto.woken_timer_step_ids)
            except Exception as exc:  # noqa: BLE001 - Shard boundary isolation: unhandled error on one shard must not starve ticks on remaining healthy shards
                logger.error(
                    "ip_stitch_tick_shard_exception",
                    shard_name=shard_name,
                    error=str(exc),
                )
                continue

        return Result.ok(
            StitchWorkerTickResultDTO(
                completed_step_ids=tuple(completed),
                failed_or_retried_step_ids=tuple(failed),
                parked_step_ids=tuple(parked),
                woken_timer_step_ids=tuple(woken),
            )
        )


__all__ = [
    "IpStitchCanonicalDispatcherAdapter",
    "IpStitchWorkerTickAdapter",
]
