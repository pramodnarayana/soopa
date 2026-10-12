import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

import structlog
from database.router import DatabaseRouter
from dotenv import load_dotenv
from edi.adapters.outbound.database.tenant_resolver import (
    TenantResolver,
)
from edi.adapters.outbound.database.tenant_uow_provider import (
    TenantUowProvider,
)
from edi.adapters.outbound.pipeline.transformer import BotsTransformerAdapter
from edi.adapters.outbound.pubsub.publisher_factory import create_edi_pipeline_publisher
from edi.application.use_cases.pipeline.delivery_router_use_case import DeliveryRouterUseCase
from edi.application.use_cases.pipeline.delivery_use_case import DeliveryUseCase
from edi.application.use_cases.pipeline.dispatch_inbound_transform_use_case import (
    DispatchInboundTransformUseCase,
)
from edi.application.use_cases.pipeline.dispatch_outbound_transform_use_case import (
    DispatchOutboundTransformUseCase,
)
from edi.application.use_cases.pipeline.pipeline_lifecycle_use_case import PipelineLifecycleUseCase
from edi.domain.enums import EdiDirection, PipelineEventType
from edi.ports.outbound.transformer_port import TransformerPort
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.provider import PubSubProvider

from worker.adapters.inbound.workers.edi_data_plane_event_dispatcher import (
    EdiDataPlaneEventDispatcher,
    EdiDataPlaneEventMessage,
)
from worker.domain.edi_data_plane_route_registry import EdiDataPlaneRouteRegistry
from worker.settings import WorkerSettings, get_settings

UowFactory = Callable[[], AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]]

load_dotenv()
logger = structlog.get_logger(__name__)


def _setup_registry(
    transformer: TransformerPort,
    settings: WorkerSettings,
    uow_provider: TenantUowProvider,
) -> EdiDataPlaneEventDispatcher:
    publisher = create_edi_pipeline_publisher(
        compute_queue_url=settings.sqs.compute_queue_url,
        orchestrator_queue_url=settings.sqs.orchestrator_queue_url,
        deliver_queue_url=settings.sqs.deliver_queue_url,
        region_name=settings.aws.resolved_region,
        endpoint_url=settings.aws.endpoint_url,
    )

    def router_factory(uow_fact: UowFactory) -> DeliveryRouterUseCase:
        return DeliveryRouterUseCase(uow_factory=uow_fact, publisher=publisher)

    registry = EdiDataPlaneRouteRegistry()

    async def run_inbound(e: EdiDataPlaneEventMessage, uow_fact: UowFactory) -> None:
        await DispatchInboundTransformUseCase(
            uow_fact, transformer, settings, publisher=publisher
        ).execute(e.trace_id, idempotency_key=e.idempotency_key)

    async def run_outbound(e: EdiDataPlaneEventMessage, uow_fact: UowFactory) -> None:
        await DispatchOutboundTransformUseCase(
            uow_fact, transformer, settings, publisher=publisher
        ).execute(e.trace_id, idempotency_key=e.idempotency_key)

    async def run_transform_successful(
        e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]
    ) -> None:
        await PipelineLifecycleUseCase(uow_fact, publisher=publisher).handle_transform_successful(
            e.tenant_id, e.idempotency_key, e.payload
        )

    async def run_transform_failed(
        e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]
    ) -> None:
        await PipelineLifecycleUseCase(uow_fact, publisher=publisher).handle_transform_failed(
            e.tenant_id, e.idempotency_key, e.payload
        )

    async def run_delivery_successful(
        e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]
    ) -> None:
        await PipelineLifecycleUseCase(uow_fact, publisher=publisher).handle_delivery_successful(
            e.tenant_id, e.idempotency_key, e.payload
        )

    async def run_delivery_failed(
        e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]
    ) -> None:
        await PipelineLifecycleUseCase(uow_fact, publisher=publisher).handle_delivery_failed(
            e.tenant_id, e.idempotency_key, e.payload
        )

    async def run_deliver(e: EdiDataPlaneEventMessage, uow_fact: UowFactory) -> None:
        await DeliveryUseCase(router_factory=lambda: router_factory(uow_fact)).execute(
            trace_id=e.trace_id, idempotency_key=e.idempotency_key
        )

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
        event_type=PipelineEventType.TRANSFORMATION_SUCCESSFUL.value,
        direction=None,
        factory=run_transform_successful,
    )
    registry.register(
        event_type=PipelineEventType.TRANSFORMATION_FAILED.value,
        direction=None,
        factory=run_transform_failed,
    )
    registry.register(
        event_type=PipelineEventType.DELIVERY_REQUESTED.value,
        direction=None,
        factory=run_deliver,
    )
    registry.register(
        event_type=PipelineEventType.DELIVERY_SUCCESSFUL.value,
        direction=None,
        factory=run_delivery_successful,
    )
    registry.register(
        event_type=PipelineEventType.DELIVERY_FAILED.value,
        direction=None,
        factory=run_delivery_failed,
    )

    async def route_event(event: EdiDataPlaneEventMessage) -> None:
        uow_factory = await uow_provider.get_uow_factory(event.tenant_id)
        await registry.route(event, uow_factory)

    return EdiDataPlaneEventDispatcher(callback=route_event)


from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async


class EdiOrchestratorWorkerModule(LaunchableWorker):
    def __init__(self) -> None:
        self.db_router: DatabaseRouter | None = None
        self.orchestrator_manager: SqsConsumerManager | None = None

    async def start(self) -> None:
        logger.info("orchestrator_worker_starting")
        settings = get_settings()
        aws_endpoint = settings.aws.endpoint_url
        s3_bucket = settings.s3.bucket

        self.db_router = DatabaseRouter(
            global_db_url=settings.database.global_url,
            shard_overrides=settings.database.shard_overrides,
        )
        resolver = TenantResolver(self.db_router)

        transformer = BotsTransformerAdapter()

        uow_provider = TenantUowProvider(
            resolver=resolver,
            db_router=self.db_router,
            settings=settings,
            s3_bucket=s3_bucket,
            aws_endpoint=aws_endpoint,
        )

        consumer = _setup_registry(transformer, settings, uow_provider)

        self.orchestrator_manager = PubSubProvider.create_consumer_manager(
            queue_url=settings.sqs.orchestrator_queue_url,
            handler=consumer.handle,
            region_name=settings.aws.resolved_region,
            endpoint_url=aws_endpoint,
        )
        assert self.orchestrator_manager is not None
        self.orchestrator_manager.start()

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        if self.orchestrator_manager and self.orchestrator_manager.task:
            return [self.orchestrator_manager.task]
        return []

    async def stop(self) -> None:
        logger.info("data_worker.shutting_down_gracefully")
        if self.orchestrator_manager:
            results = await asyncio.gather(
                self.orchestrator_manager.stop(),
                return_exceptions=True,
            )
            for res in results:
                if isinstance(res, Exception):
                    logger.error("manager_stop_failed", exc_info=res)

        if self.db_router:
            await self.db_router.close_all()


async def main(stop_event: asyncio.Event | None = None) -> None:
    module = EdiOrchestratorWorkerModule()
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)
