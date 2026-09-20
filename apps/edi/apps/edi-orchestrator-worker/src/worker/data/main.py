import asyncio
import signal
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import structlog
from database.router import DatabaseRouter
from dotenv import load_dotenv
from edi.adapters.outbound.database.data_plane.postgres_idempotency_repository import (
    SqlAlchemyEdiIdempotencyRepository,
)
from edi.adapters.outbound.database.tenant_resolver import (
    TenantResolver,
)
from edi.adapters.outbound.database.tenant_uow_provider import (
    TenantUowProvider,
)
from edi.adapters.outbound.pipeline.transformer import BotsTransformerAdapter
from edi.application.use_cases.pipeline.delivery_router_use_case import DeliveryRouterUseCase
from edi.application.use_cases.pipeline.delivery_use_case import DeliveryUseCase
from edi.application.use_cases.pipeline.dispatch_inbound_transform_use_case import (
    DispatchInboundTransformUseCase,
)
from edi.application.use_cases.pipeline.dispatch_outbound_transform_use_case import (
    DispatchOutboundTransformUseCase,
)
from edi.application.use_cases.pipeline.pipeline_lifecycle_use_case import PipelineLifecycleUseCase
from edi.config.settings import AppSettings, get_settings
from edi.domain.enums import EdiDirection, PipelineEventType
from edi.ports.outbound.transformer_port import TransformerPort
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager

from worker.adapters.inbound.workers.edi_data_plane_event_dispatcher import (
    EdiDataPlaneEventDispatcher,
    EdiDataPlaneEventMessage,
)
from worker.domain.edi_data_plane_route_registry import EdiDataPlaneRouteRegistry

UowFactory = Callable[[], AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]]

load_dotenv()
logger = structlog.get_logger(__name__)


def _setup_registry(
    transformer: TransformerPort,
    settings: AppSettings,
    uow_provider: TenantUowProvider,
) -> EdiDataPlaneEventDispatcher:
    def router_factory(uow_fact: UowFactory) -> DeliveryRouterUseCase:
        return DeliveryRouterUseCase(uow_factory=uow_fact)

    registry = EdiDataPlaneRouteRegistry()

    async def run_inbound(e: EdiDataPlaneEventMessage, uow_fact: UowFactory) -> None:
        async with uow_fact() as uow:
            await DispatchInboundTransformUseCase(uow, transformer, settings).execute(e.trace_id)

    async def run_outbound(e: EdiDataPlaneEventMessage, uow_fact: UowFactory) -> None:
        async with uow_fact() as uow:
            await DispatchOutboundTransformUseCase(uow, transformer, settings).execute(e.trace_id)

    async def run_transform_lifecycle(
        e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]
    ) -> None:
        async with uow_fact() as uow:
            await PipelineLifecycleUseCase(uow).handle_transform_completed(e.payload)

    async def run_delivery_lifecycle(
        e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]
    ) -> None:
        async with uow_fact() as uow:
            await PipelineLifecycleUseCase(uow).handle_delivery_completed(e.payload)

    async def run_deliver(e: EdiDataPlaneEventMessage, uow_fact: UowFactory) -> None:
        await DeliveryUseCase(
            uow_factory=uow_fact, router_factory=lambda: router_factory(uow_fact)
        ).execute(trace_id=e.trace_id, idempotency_key=e.idempotency_key)

    registry.register(
        event_type=PipelineEventType.TRANSFORMATION_REQUESTED.value,
        direction=EdiDirection.INBOUND.value,
        factory=run_inbound,
    )
    registry.register(
        event_type=PipelineEventType.TRANSFORMATION_REQUESTED.value,
        direction=EdiDirection.OUTBOUND.value,
        factory=run_outbound,
    )
    registry.register(
        event_type=PipelineEventType.TRANSFORMATION_COMPLETED.value,
        direction=None,
        factory=run_transform_lifecycle,
    )
    registry.register(
        event_type=PipelineEventType.DELIVERY_REQUESTED.value,
        direction=None,
        factory=run_deliver,
    )
    registry.register(
        event_type=PipelineEventType.DELIVERY_COMPLETED.value,
        direction=None,
        factory=run_delivery_lifecycle,
    )

    async def route_event(event: EdiDataPlaneEventMessage) -> None:
        uow_factory = await uow_provider.get_uow_factory(event.tenant_id)
        await registry.route(event, uow_factory)

    return EdiDataPlaneEventDispatcher(callback=route_event)


async def main() -> None:
    settings = get_settings()
    aws_endpoint = settings.aws.endpoint_url
    s3_bucket = "soopaedi-dev"

    db_router = DatabaseRouter(
        global_db_url=settings.database.global_url,
        shard_overrides=settings.database.shard_overrides,
    )
    resolver = TenantResolver(db_router)
    idempotency_repo = SqlAlchemyEdiIdempotencyRepository(db_router, resolver)

    transformer = BotsTransformerAdapter()

    uow_provider = TenantUowProvider(
        resolver=resolver,
        db_router=db_router,
        settings=settings,
        s3_bucket=s3_bucket,
        aws_endpoint=aws_endpoint,
    )

    consumer = _setup_registry(transformer, settings, uow_provider)

    orchestrator_consumer = AwsSqsConsumer(
        queue_url=settings.sqs.orchestrator_queue_url,
        region_name=settings.aws.resolved_region,
        endpoint_url=aws_endpoint,
    )
    orchestrator_manager = SqsConsumerManager(
        consumer=orchestrator_consumer,
        queue_name=settings.sqs.orchestrator_queue_url.rsplit("/", 1)[-1],
        handler=consumer.handle,
        idempotency_repo=idempotency_repo,
    )
    orchestrator_manager.start()

    # ─────────────────────────────────────────────────────────────
    # Run all workers concurrently
    # ─────────────────────────────────────────────────────────────
    stop_event = asyncio.Event()
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop_event.set)

        tasks_to_wait: list[asyncio.Task[Any]] = [asyncio.create_task(stop_event.wait())]
        for mgr in [orchestrator_manager]:
            # Use the new task property once it is exposed
            task = getattr(mgr, "task", getattr(mgr, "_task", None))
            if task:
                tasks_to_wait.append(task)

        done, _pending = await asyncio.wait(tasks_to_wait, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task is not tasks_to_wait[0] and task.exception():
                exc = task.exception()
                logger.error("sqs_consumer_manager_failed", exc_info=exc)
                if exc:
                    raise exc
    finally:
        logger.info("data_worker.shutting_down_gracefully")
        results = await asyncio.gather(
            orchestrator_manager.stop(),
            return_exceptions=True,
        )
        for res in results:
            if isinstance(res, Exception):
                logger.error("manager_stop_failed", exc_info=res)

        await db_router.close_all()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        # Check if it's a Pydantic ValidationError without adding a hard dependency at the top
        if e.__class__.__name__ == "ValidationError":
            from pydantic import ValidationError

            all_errors = e.errors() if isinstance(e, ValidationError) else []

            missing_fields = [
                f"{'.'.join(str(loc_item) for loc_item in err.get('loc', []))} ({err.get('msg', '')})"
                for err in all_errors
                if err.get("type") in ("missing", "value_error.missing")
            ]
            invalid_fields = [
                f"{'.'.join(str(loc_item) for loc_item in err.get('loc', []))} ({err.get('msg', '')})"
                for err in all_errors
                if err.get("type") not in ("missing", "value_error.missing")
            ]

            if missing_fields:
                logger.exception(
                    "worker_startup_configuration_error",
                    reason="One or more required environment variables are missing from your .env file.",
                    missing_fields=missing_fields,
                    remedy="Please check .env.example and ensure all required variables are set.",
                )
            if invalid_fields:
                logger.exception(
                    "worker_startup_configuration_error",
                    reason="One or more environment variables have invalid configured values.",
                    invalid_fields=invalid_fields,
                )
        else:
            logger.exception("worker_startup_failed", reason="Startup initialization error")
        raise
