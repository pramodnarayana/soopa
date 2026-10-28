"""LaunchableWorker entrypoint for `ip-dp-jobs-worker` (IP Data Plane Outbox Drain Relay, Sweeper, & Retention)."""

from __future__ import annotations

import asyncio
from typing import cast

import structlog
from database.router import DatabaseRouter, DatabaseRouterPort
from ip.engine.adapters.outbound.database.models.data_plane import (
    IpDataPlaneOutboxRecord,
    IpProcessedEventModel,
    IpTraceEventModel,
)
from ip.engine.adapters.outbound.pubsub.publisher_factory import (
    create_ip_dp_outbox_publisher,
)
from ip.engine.domain.enums import IpJobName, IpOutboxSource
from ip.engine.settings import IpEngineSettings, get_ip_engine_settings
from observability import ObservabilityProvider
from outbox.adapters.inbound.multi_shard_outbox_drain_relay import (
    MultiShardOutboxDrainRelay,
)
from outbox.adapters.outbound.sqlalchemy_sharded_outbox_repository import (
    SqlAlchemyShardedOutboxRepository,
)
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from pubsub.ports.message_consumer_port import MessageConsumerPort
from pubsub.provider import PubSubProvider
from seedwork.domain.types import JsonDict
from seedwork.infra.worker import LaunchableWorker, run_worker_app, run_worker_app_async
from strace.adapters.retention_repository import SqlAlchemyShardedTraceRetentionRepository
from strace.application.clean_trace_retention_use_case import (
    CleanTraceRetentionCommand,
    CleanTraceRetentionUseCase,
)

logger = structlog.get_logger(__name__)


class IpDpJobsWorkerModule(LaunchableWorker):
    """Physical worker bulkhead for IP Data Plane (`public.ip_outbox`) multi-shard drain relay, sweeper, and retention."""

    def __init__(
        self,
        settings: IpEngineSettings | None = None,
        *,
        db_router: DatabaseRouterPort | None = None,
        publisher: OutboxPublisherPort | None = None,
        jobs_consumer: MessageConsumerPort | None = None,
    ) -> None:
        self._initial_settings = settings
        self.settings: IpEngineSettings | None = settings
        self.db_router: DatabaseRouterPort | None = db_router
        self._owns_db_router: bool = db_router is None
        self._injected_publisher = publisher
        self._jobs_consumer = jobs_consumer

        self.dp_outbox_repo: SqlAlchemyShardedOutboxRepository | None = None
        self.trace_retention_repo: SqlAlchemyShardedTraceRetentionRepository | None = None
        self.dp_publisher: OutboxPublisherPort | None = publisher
        self.dp_outbox_relay: MultiShardOutboxDrainRelay | None = None
        self.dp_sweeper: OutboxSweeperUseCase | None = None
        self.dp_cleaner: OutboxCleanerUseCase | None = None
        self.trace_retention_use_case: CleanTraceRetentionUseCase | None = None
        self.job_dispatcher: MessageDispatcher | None = None
        self.dp_jobs_manager: SqsConsumerManager | None = None

    async def start(self) -> None:
        logger.info("ip_dp_jobs_worker_starting")
        self.settings = self._initial_settings or get_ip_engine_settings()

        if self.db_router is None:
            self.db_router = DatabaseRouter(
                global_db_url=self.settings.global_database_url,
                pool_size=self.settings.db_pool_size,
                max_overflow=self.settings.db_max_overflow,
            )
            self._owns_db_router = True

        self.dp_outbox_repo = SqlAlchemyShardedOutboxRepository(
            self.db_router,
            model_cls=IpDataPlaneOutboxRecord,
            app_slug="ip",
            source=IpOutboxSource.DATA_PLANE.value,
        )
        self.trace_retention_repo = SqlAlchemyShardedTraceRetentionRepository(
            self.db_router,
            app_slug="ip",
            trace_event_model_cls=IpTraceEventModel,
            processed_event_model_cls=IpProcessedEventModel,
        )
        self.dp_publisher = self._injected_publisher or create_ip_dp_outbox_publisher(self.settings)

        self.dp_outbox_relay = MultiShardOutboxDrainRelay(
            repository=self.dp_outbox_repo,
            publisher=self.dp_publisher,
            batch_size=self.settings.outbox_batch_size,
            lock_lease_ms=self.settings.outbox_lock_lease_ms,
        )
        self.dp_sweeper = OutboxSweeperUseCase(
            repository=self.dp_outbox_repo,
            publisher=self.dp_publisher,
            lock_lease_ms=self.settings.outbox_lock_lease_ms,
            max_concurrent_events=self.settings.outbox_batch_size,
        )
        retention_days = max(1, self.settings.outbox_retention_hours // 24)
        self.dp_cleaner = OutboxCleanerUseCase(
            repository=self.dp_outbox_repo,
            retention_days=retention_days,
        )
        self.trace_retention_use_case = CleanTraceRetentionUseCase(
            repository=self.trace_retention_repo,
        )

        self.dp_outbox_relay.start()
        self._wire_jobs_consumer(self.settings, retention_days=retention_days)
        logger.info("ip_dp_jobs_worker_started")

    def _wire_jobs_consumer(
        self,
        settings: IpEngineSettings,
        *,
        retention_days: int,
    ) -> None:
        dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME.value)

        async def _handle_sweeper(_msg: JsonDict) -> None:
            if self.dp_sweeper is not None:
                await self.dp_sweeper.execute()

        async def _handle_outbox_cleanup(_msg: JsonDict) -> None:
            if self.dp_cleaner is not None:
                await self.dp_cleaner.execute()

        async def _handle_trace_retention(_msg: JsonDict) -> None:
            if self.trace_retention_use_case is not None:
                await self.trace_retention_use_case.execute(
                    CleanTraceRetentionCommand(
                        trace_retention_days=settings.trace_retention_days,
                        processed_event_retention_days=retention_days,
                    )
                )

        dispatcher.subscribe(IpJobName.IP_DATA_PLANE_OUTBOX_SWEEPER.value, _handle_sweeper)
        dispatcher.subscribe(IpJobName.IP_DATA_PLANE_OUTBOX_CLEANUP.value, _handle_outbox_cleanup)
        dispatcher.subscribe(IpJobName.IP_DATA_RETENTION_CLEANUP.value, _handle_trace_retention)
        self.job_dispatcher = dispatcher

        if self._jobs_consumer is not None:
            self.dp_jobs_manager = SqsConsumerManager(
                consumer=self._jobs_consumer,
                handler=dispatcher.dispatch,
                queue_name="ip-dp-jobs",
            )
            self.dp_jobs_manager.start()
        elif settings.ip_data_plane_jobs_queue_url:
            self.dp_jobs_manager = PubSubProvider.create_consumer_manager(
                queue_url=settings.ip_data_plane_jobs_queue_url,
                handler=dispatcher.dispatch,
                region_name=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
            )
            self.dp_jobs_manager.start()

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        tasks: list[asyncio.Task[object]] = []
        if self.dp_outbox_relay is not None:
            tasks.extend(cast(list[asyncio.Task[object]], self.dp_outbox_relay.background_tasks()))
        if self.dp_jobs_manager is not None:
            tasks.extend(cast(list[asyncio.Task[object]], self.dp_jobs_manager.background_tasks()))
        return tasks

    async def stop(self) -> None:
        logger.info("ip_dp_jobs_worker_stopping")
        if self.dp_jobs_manager is not None:
            await self.dp_jobs_manager.stop()
        if self.dp_outbox_relay is not None:
            await self.dp_outbox_relay.stop()
        if self.db_router is not None and self._owns_db_router:
            await self.db_router.close_all()
        logger.info("ip_dp_jobs_worker_stopped")


async def main(stop_event: asyncio.Event | None = None) -> None:
    ObservabilityProvider.auto_configure_from_env("ip-dp-jobs-worker")
    module = IpDpJobsWorkerModule()
    await run_worker_app_async(module, stop_event=stop_event)


if __name__ == "__main__":
    run_worker_app(main)

__all__ = ["IpDpJobsWorkerModule", "main"]
