import structlog
from database.router import DatabaseRouter, DatabaseRouterPort
from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
from edi.bootstrap.publisher_factory import create_edi_pipeline_publisher
from edi.domain.constants import EdiConstants
from edi.domain.enums import EdiJobName, EdiOutboxSource
from outbox.adapters.inbound.multi_shard_outbox_drain_relay import MultiShardOutboxDrainRelay
from outbox.adapters.outbound.sqlalchemy_sharded_outbox_repository import (
    SqlAlchemyShardedOutboxRepository,
)
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from outbox.application.outbox_sweeper_use_case import (
    LeaseOnlyOutboxSweeperUseCase,
    OutboxSweeperPort,
    OutboxSweeperUseCase,
)
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from outbox.ports.outbox_relay_port import OutboxRelayPort
from outbox.ports.shard_outbox_drain_port import ShardOutboxDrainPort
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from pubsub.domain.enums import is_database_queue_uri
from pubsub.ports.consumer_manager_port import ConsumerManagerPort
from pubsub.provider import PubSubProvider
from seedwork.domain.types import JsonDict

from edi_dp_jobs_worker.adapters.inbound.jobs.edi_data_plane_outbox_cleanup_job import (
    EdiDataPlaneOutboxCleanupJobHandler,
)
from edi_dp_jobs_worker.adapters.inbound.jobs.edi_data_plane_outbox_sweeper_job import (
    EdiDataPlaneOutboxSweeperJobHandler,
)
from edi_dp_jobs_worker.adapters.inbound.jobs.edi_data_retention_cleanup_job import (
    EdiDataRetentionCleanupJobHandler,
)
from edi_dp_jobs_worker.adapters.outbound.database.sqlalchemy_edi_data_retention_cleanup_repository import (
    SqlAlchemyEdiDataRetentionCleanupRepository,
)
from edi_dp_jobs_worker.application.use_cases.edi_data_retention_cleanup_use_case import (
    EdiDataRetentionCleanupUseCase,
)
from edi_dp_jobs_worker.settings import WorkerSettings, get_settings

logger = structlog.get_logger(__name__)


class WorkerContainer:
    """Dependency Injection container for the EDI Data Plane Jobs Worker."""

    def __init__(
        self,
        settings: WorkerSettings | None = None,
        *,
        db_router: DatabaseRouterPort | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.db_router = db_router or DatabaseRouter(
            global_db_url=self.settings.database.global_url,
            shard_overrides=self.settings.database.shard_overrides,
        )

        self.dp_outbox_relay: OutboxRelayPort | None = None
        self.dp_manager: ConsumerManagerPort | None = None
        self.dp_cleanup_job_handler: EdiDataPlaneOutboxCleanupJobHandler | None = None
        self.retention_cleanup_job_handler: EdiDataRetentionCleanupJobHandler | None = None
        self.dp_sweeper_job_handler: EdiDataPlaneOutboxSweeperJobHandler | None = None

    def wire(self) -> None:
        sharded_drain_repo = SqlAlchemyShardedOutboxRepository(
            db_router=self.db_router,
            model_cls=DataPlaneOutbox,
            app_slug=EdiConstants.EDI_APP_SLUG.value,
            source=EdiOutboxSource.EDI_DATA_PLANE.value,
            min_pending_age_seconds=0,
        )
        sharded_sweeper_repo = SqlAlchemyShardedOutboxRepository(
            db_router=self.db_router,
            model_cls=DataPlaneOutbox,
            app_slug=EdiConstants.EDI_APP_SLUG.value,
            source=EdiOutboxSource.EDI_DATA_PLANE.value,
            min_pending_age_seconds=60,
        )

        if is_database_queue_uri(self.settings.sqs.orchestrator_queue_url):
            logger.info("edi_dp_outbox_relay_skipped_direct_single_queue_mode")
            sweeper_strategy: OutboxSweeperPort = LeaseOnlyOutboxSweeperUseCase(
                repository=sharded_sweeper_repo,
                lock_lease_ms=30000,
            )
        else:
            publisher = create_edi_pipeline_publisher(
                compute_queue_url=self.settings.sqs.compute_queue_url,
                orchestrator_queue_url=self.settings.sqs.orchestrator_queue_url,
                deliver_queue_url=self.settings.sqs.deliver_queue_url,
                region_name=self.settings.aws.resolved_region,
                endpoint_url=self.settings.aws.endpoint_url,
            )
            self._wire_outbox_relay(sharded_drain_repo, publisher)
            sweeper_strategy = OutboxSweeperUseCase(
                repository=sharded_sweeper_repo,
                publisher=publisher,
            )

        self._wire_scheduled_jobs(sharded_sweeper_repo, sweeper_strategy)
        self._wire_jobs_consumers()

    def _wire_outbox_relay(
        self,
        repository: ShardOutboxDrainPort,
        publisher: OutboxPublisherPort,
    ) -> None:
        self.dp_outbox_relay = MultiShardOutboxDrainRelay(
            repository=repository,
            publisher=publisher,
            batch_size=500,
            shard_concurrency=5,
            poll_interval_seconds=0.2,
        )

    def _wire_scheduled_jobs(
        self,
        sharded_outbox_repo: SqlAlchemyShardedOutboxRepository[DataPlaneOutbox],
        sweeper_strategy: OutboxSweeperPort,
    ) -> None:
        self.dp_cleanup_job_handler = EdiDataPlaneOutboxCleanupJobHandler(
            OutboxCleanerUseCase(sharded_outbox_repo)
        )

        retention_cleanup_repo = SqlAlchemyEdiDataRetentionCleanupRepository(
            db_router=self.db_router
        )
        self.retention_cleanup_job_handler = EdiDataRetentionCleanupJobHandler(
            EdiDataRetentionCleanupUseCase(retention_cleanup_repo)
        )

        self.dp_sweeper_job_handler = EdiDataPlaneOutboxSweeperJobHandler(sweeper_strategy)

    def _wire_jobs_consumers(self) -> None:
        dp_dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME.value)

        async def dp_cleanup_handler(msg: JsonDict) -> None:
            if self.dp_cleanup_job_handler:
                await self.dp_cleanup_job_handler.execute()

        async def retention_cleanup_handler(msg: JsonDict) -> None:
            if self.retention_cleanup_job_handler:
                await self.retention_cleanup_job_handler.execute()

        async def dp_sweeper_handler(msg: JsonDict) -> None:
            if self.dp_sweeper_job_handler:
                await self.dp_sweeper_job_handler.execute()

        dp_dispatcher.subscribe(EdiJobName.EDI_DATA_PLANE_OUTBOX_CLEANUP.value, dp_cleanup_handler)
        dp_dispatcher.subscribe(
            EdiJobName.EDI_DATA_RETENTION_CLEANUP.value, retention_cleanup_handler
        )
        dp_dispatcher.subscribe(EdiJobName.EDI_DATA_PLANE_OUTBOX_SWEEPER.value, dp_sweeper_handler)

        self.dp_manager = PubSubProvider.create_consumer_manager(
            source_uri=self.settings.sqs.data_plane_jobs_queue_url,
            handler=dp_dispatcher.dispatch,
            region_name=self.settings.aws.resolved_region,
            endpoint_url=self.settings.aws.endpoint_url,
            session_factory=self.db_router.global_session_scope,
            database_url=self.settings.database.global_url,
        )

    async def start(self) -> None:
        if self.dp_manager:
            self.dp_manager.start()
        if self.dp_outbox_relay:
            self.dp_outbox_relay.start()

    async def dispose(self) -> None:
        try:
            if self.dp_manager:
                await self.dp_manager.stop()
            if self.dp_outbox_relay:
                await self.dp_outbox_relay.stop()
        finally:
            if self.db_router:
                await self.db_router.close_all()
