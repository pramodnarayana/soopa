"""LaunchableWorker Composition Root for `ip-cp-jobs-worker` (IP Control Plane Outbox Relay, Sweeper, & Retention)."""

from __future__ import annotations

import asyncio

import structlog
from database.router import DatabaseRouter, DatabaseRouterPort
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from outbox.ports.outbox_cleanup_repository_port import OutboxCleanupRepositoryPort
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from outbox.ports.outbox_relay_port import OutboxRelayPort
from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from pubsub.ports.message_consumer_port import MessageConsumerPort
from pubsub.provider import PubSubProvider
from seedwork.domain.types import JsonDict
from seedwork.infra.worker import LaunchableWorker

from ip.engine.bootstrap.container import (
    create_ip_cp_outbox_components,
    create_ip_cp_outbox_relay,
)
from ip.engine.domain.enums import (
    IpJobName,
    IpOutboxChannel,
)
from ip.engine.settings import IpEngineSettings, get_ip_engine_settings

logger = structlog.get_logger(__name__)


class IpCpJobsWorkerModule(LaunchableWorker):
    """Physical worker bulkhead for IP Control Plane (`ip.outbox`) relay, sweeper, and retention."""

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

        self.cp_outbox_repo: OutboxRepositoryPort | None = None
        self.cp_cleanup_repo: OutboxCleanupRepositoryPort | None = None
        self.cp_publisher: OutboxPublisherPort | None = publisher
        self.cp_processor: OutboxProcessorUseCase | None = None
        self.cp_sweeper: OutboxSweeperUseCase | None = None
        self.cp_cleaner: OutboxCleanerUseCase | None = None
        self.cp_outbox_relay: OutboxRelayPort | None = None
        self.job_dispatcher: MessageDispatcher | None = None
        self.cp_jobs_manager: SqsConsumerManager | None = None

    async def start(self) -> None:
        logger.info("ip_cp_jobs_worker_starting")
        self.settings = self._initial_settings or get_ip_engine_settings()

        if self.db_router is None:
            self.db_router = DatabaseRouter(
                global_db_url=self.settings.global_database_url,
                pool_size=self.settings.db_pool_size,
                max_overflow=self.settings.db_max_overflow,
            )
            self._owns_db_router = True

        (
            self.cp_outbox_repo,
            self.cp_cleanup_repo,
            self.cp_publisher,
        ) = create_ip_cp_outbox_components(
            db_router=self.db_router,
            settings=self.settings,
            publisher=self._injected_publisher,
        )

        self.cp_processor = OutboxProcessorUseCase(
            repository=self.cp_outbox_repo,
            publisher=self.cp_publisher,
            max_concurrent_events=self.settings.outbox_batch_size,
            lock_lease_ms=self.settings.outbox_lock_lease_ms,
        )
        self.cp_sweeper = OutboxSweeperUseCase(
            repository=self.cp_outbox_repo,
            publisher=self.cp_publisher,
            lock_lease_ms=self.settings.outbox_lock_lease_ms,
            max_concurrent_events=self.settings.outbox_batch_size,
        )
        retention_days = max(1, self.settings.outbox_retention_hours // 24)
        self.cp_cleaner = OutboxCleanerUseCase(
            repository=self.cp_cleanup_repo,
            retention_days=retention_days,
        )

        self.cp_outbox_relay = create_ip_cp_outbox_relay(
            processor=self.cp_processor,
            database_url=self.settings.global_database_url,
            listen_channel=IpOutboxChannel.CONTROL_PLANE.value,
            fallback_poll_interval=max(1, int(self.settings.outbox_fallback_poll_sec)),
        )
        self.cp_outbox_relay.start()

        self._wire_jobs_consumer(self.settings)
        logger.info("ip_cp_jobs_worker_started")

    def _wire_jobs_consumer(self, settings: IpEngineSettings) -> None:
        dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME.value)

        async def _handle_sweeper(_msg: JsonDict) -> None:
            if self.cp_sweeper is not None:
                await self.cp_sweeper.execute()

        async def _handle_cleanup(_msg: JsonDict) -> None:
            if self.cp_cleaner is not None:
                await self.cp_cleaner.execute()

        dispatcher.subscribe(IpJobName.IP_CONTROL_PLANE_OUTBOX_SWEEPER.value, _handle_sweeper)
        dispatcher.subscribe(IpJobName.IP_CONTROL_PLANE_OUTBOX_CLEANUP.value, _handle_cleanup)
        self.job_dispatcher = dispatcher

        if self._jobs_consumer is not None:
            self.cp_jobs_manager = SqsConsumerManager(
                consumer=self._jobs_consumer,
                handler=dispatcher.dispatch,
                queue_name="ip-cp-jobs",
            )
            self.cp_jobs_manager.start()
        elif settings.ip_control_plane_jobs_queue_url:
            self.cp_jobs_manager = PubSubProvider.create_consumer_manager(
                queue_url=settings.ip_control_plane_jobs_queue_url,
                handler=dispatcher.dispatch,
                region_name=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
            )
            self.cp_jobs_manager.start()

    def get_background_tasks(self) -> list[asyncio.Task[object]]:
        tasks: list[asyncio.Task[object]] = []
        if self.cp_outbox_relay is not None:
            tasks.extend(self.cp_outbox_relay.background_tasks())
        if self.cp_jobs_manager is not None:
            tasks.extend(self.cp_jobs_manager.background_tasks())
        return tasks

    async def stop(self) -> None:
        logger.info("ip_cp_jobs_worker_stopping")
        if self.cp_jobs_manager is not None:
            await self.cp_jobs_manager.stop()
        if self.cp_outbox_relay is not None:
            await self.cp_outbox_relay.stop()
        if self.db_router is not None and self._owns_db_router:
            await self.db_router.close_all()
        logger.info("ip_cp_jobs_worker_stopped")


__all__ = ["IpCpJobsWorkerModule"]
