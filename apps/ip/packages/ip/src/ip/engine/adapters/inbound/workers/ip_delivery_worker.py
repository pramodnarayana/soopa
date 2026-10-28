"""LaunchableWorker entrypoint for `ip-delivery-worker` (Layer 5 & Layer 1 External I/O)."""

from __future__ import annotations

import asyncio
from typing import cast

import structlog
from database.router import DatabaseRouter, DatabaseRouterPort
from dependency_injector import providers
from ip.engine.adapters.inbound.workers.ip_delivery_route_registry import (
    IpDeliveryRouteRegistry,
)
from ip.engine.adapters.outbound.database.control_plane.uow import (
    SqlAlchemyIpControlPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.database.tenant_resolver import IpTenantResolver
from ip.engine.application.use_cases.delivery.deliver_outbound_record_use_case import (
    DeliverOutboundRecordCommand,
    DeliverOutboundRecordResponse,
)
from ip.engine.application.use_cases.ingestion.fetch_record_use_case import (
    FetchRecordCommand,
    FetchRecordResultDTO,
)
from ip.engine.application.use_cases.ingestion.run_sync_use_case import (
    RunSyncCommand,
    RunSyncResultDTO,
)
from ip.engine.application.worker_ports import (
    IpFetchRecordExecutorPort,
    IpOutboundDeliveryExecutorPort,
    IpRunSyncExecutorPort,
)
from ip.engine.container import Container
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.settings import IpEngineSettings, get_ip_engine_settings
from observability import ObservabilityProvider
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.envelope_dispatcher import EventEnvelopeDispatcher
from pubsub.ports.message_consumer_port import MessageConsumerPort
from pubsub.provider import PubSubProvider
from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async

logger = structlog.get_logger(__name__)


class _SessionScopedIpOutboundDeliveryExecutor(IpOutboundDeliveryExecutorPort):
    """Opens an isolated Control Plane GlobalSession per outbound delivery execution."""

    def __init__(self, db_router: DatabaseRouterPort, container: Container) -> None:
        self._db_router = db_router
        self._container = container

    async def execute(
        self, command: DeliverOutboundRecordCommand
    ) -> Result[DeliverOutboundRecordResponse, IpError]:
        async for global_session in self._db_router.get_global_session():
            cp_uow = SqlAlchemyIpControlPlaneUnitOfWork(global_session)
            token_mgr = self._container.token_manager(control_plane_uow=cp_uow)
            use_case = self._container.deliver_outbound_record_use_case(
                token_manager=token_mgr,
            )
            return await use_case.execute(command)
        raise RuntimeError("DatabaseRouter did not yield a GlobalSession.")


class _SessionScopedIpFetchRecordExecutor(IpFetchRecordExecutorPort):
    """Opens an isolated Control Plane GlobalSession per Fetch-on-Notify pull."""

    def __init__(self, db_router: DatabaseRouterPort, container: Container) -> None:
        self._db_router = db_router
        self._container = container

    async def execute(self, command: FetchRecordCommand) -> FetchRecordResultDTO:
        async for global_session in self._db_router.get_global_session():
            cp_uow = SqlAlchemyIpControlPlaneUnitOfWork(global_session)
            token_mgr = self._container.token_manager(control_plane_uow=cp_uow)
            use_case = self._container.fetch_record_use_case(
                control_plane_uow=cp_uow,
                token_manager=token_mgr,
            )
            return await use_case.execute(command)
        raise RuntimeError("DatabaseRouter did not yield a GlobalSession.")


class _SessionScopedIpRunSyncExecutor(IpRunSyncExecutorPort):
    """Opens an isolated Control Plane GlobalSession per checkpointed pull sync."""

    def __init__(self, db_router: DatabaseRouterPort, container: Container) -> None:
        self._db_router = db_router
        self._container = container

    async def execute(self, command: RunSyncCommand) -> RunSyncResultDTO:
        async for global_session in self._db_router.get_global_session():
            cp_uow = SqlAlchemyIpControlPlaneUnitOfWork(global_session)
            token_mgr = self._container.token_manager(control_plane_uow=cp_uow)
            use_case = self._container.run_sync_use_case(
                control_plane_uow=cp_uow,
                token_manager=token_mgr,
            )
            return await use_case.execute(command)
        raise RuntimeError("DatabaseRouter did not yield a GlobalSession.")


class IpDeliveryWorkerModule(LaunchableWorker):
    """Physical worker bulkhead for IP external network I/O (L5 Outbound & L1 Pull/Fetch).

    Consumes from both the `realtime` ($N=1$) and `bulk` ($N=K$) delivery SQS queues.
    """

    def __init__(
        self,
        settings: IpEngineSettings | None = None,
        *,
        db_router: DatabaseRouterPort | None = None,
        realtime_consumer: MessageConsumerPort | None = None,
        bulk_consumer: MessageConsumerPort | None = None,
    ) -> None:
        self._initial_settings = settings
        self.settings: IpEngineSettings | None = settings
        self.db_router: DatabaseRouterPort | None = db_router
        self._owns_db_router: bool = db_router is None
        self._realtime_consumer = realtime_consumer
        self._bulk_consumer = bulk_consumer

        self.container: Container | None = None
        self.dispatcher: EventEnvelopeDispatcher | None = None
        self.route_registry: IpDeliveryRouteRegistry | None = None
        self.realtime_manager: SqsConsumerManager | None = None
        self.bulk_manager: SqsConsumerManager | None = None

    async def start(self) -> None:
        logger.info("ip_delivery_worker_starting")
        self.settings = self._initial_settings or get_ip_engine_settings()

        if self.db_router is None:
            self.db_router = DatabaseRouter(
                global_db_url=self.settings.global_database_url,
                pool_size=self.settings.db_pool_size,
                max_overflow=self.settings.db_max_overflow,
            )
            self._owns_db_router = True

        resolver = IpTenantResolver(self.db_router)
        container = Container()
        container.config.allow_private_ips.from_value(self.settings.allow_private_ips)
        container.db_router.override(providers.Object(self.db_router))
        container.tenant_resolver.override(providers.Object(resolver))
        self.container = container

        self.route_registry = IpDeliveryRouteRegistry(
            dp_uow_provider=container.dp_uow_provider(),
            deliver_outbound_use_case=_SessionScopedIpOutboundDeliveryExecutor(
                self.db_router, container
            ),
            fetch_record_use_case=_SessionScopedIpFetchRecordExecutor(self.db_router, container),
            run_sync_use_case=_SessionScopedIpRunSyncExecutor(self.db_router, container),
            tiered_storage=container.tiered_storage(),
            max_chunk_concurrency=self.settings.delivery_chunk_concurrency,
        )
        self.dispatcher = EventEnvelopeDispatcher()
        self.route_registry.register_routes(self.dispatcher)

        self._start_queue_managers(self.settings, self.dispatcher)
        logger.info("ip_delivery_worker_started")

    def _start_queue_managers(
        self,
        settings: IpEngineSettings,
        dispatcher: EventEnvelopeDispatcher,
    ) -> None:
        if self._realtime_consumer is not None:
            self.realtime_manager = SqsConsumerManager(
                consumer=self._realtime_consumer,
                handler=dispatcher.handle,
                queue_name="ip-delivery-realtime",
            )
            self.realtime_manager.start()
        elif settings.ip_delivery_realtime_queue_url:
            self.realtime_manager = PubSubProvider.create_consumer_manager(
                queue_url=settings.ip_delivery_realtime_queue_url,
                handler=dispatcher.handle,
                region_name=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
            )
            self.realtime_manager.start()

        if self._bulk_consumer is not None:
            self.bulk_manager = SqsConsumerManager(
                consumer=self._bulk_consumer,
                handler=dispatcher.handle,
                queue_name="ip-delivery-bulk",
            )
            self.bulk_manager.start()
        elif settings.ip_delivery_bulk_queue_url:
            self.bulk_manager = PubSubProvider.create_consumer_manager(
                queue_url=settings.ip_delivery_bulk_queue_url,
                handler=dispatcher.handle,
                region_name=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
            )
            self.bulk_manager.start()

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        tasks: list[asyncio.Task[object]] = []
        if self.realtime_manager is not None:
            tasks.extend(cast(list[asyncio.Task[object]], self.realtime_manager.background_tasks()))
        if self.bulk_manager is not None:
            tasks.extend(cast(list[asyncio.Task[object]], self.bulk_manager.background_tasks()))
        return tasks

    async def stop(self) -> None:
        logger.info("ip_delivery_worker_stopping")
        if self.realtime_manager is not None:
            await self.realtime_manager.stop()
        if self.bulk_manager is not None:
            await self.bulk_manager.stop()
        if self.db_router is not None and self._owns_db_router:
            await self.db_router.close_all()
        logger.info("ip_delivery_worker_stopped")


async def main(stop_event: asyncio.Event | None = None) -> None:
    ObservabilityProvider.auto_configure_from_env("ip-delivery-worker")
    module = IpDeliveryWorkerModule()
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)

__all__ = ["IpDeliveryWorkerModule", "main"]
