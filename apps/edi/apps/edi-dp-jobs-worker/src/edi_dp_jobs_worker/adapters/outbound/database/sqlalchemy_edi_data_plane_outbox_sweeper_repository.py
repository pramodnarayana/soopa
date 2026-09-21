from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import structlog
from database.router import DatabaseRouter
from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox, ProcessedEvent
from edi.domain.enums import PipelineEventType
from sqlalchemy import and_, select

from edi_dp_jobs_worker.ports.outbound.edi_data_plane_outbox_sweeper_repository_port import (
    EdiDataPlaneOutboxSweeperRepositoryPort,
)

logger = structlog.get_logger(__name__)


class SqlAlchemyEdiDataPlaneOutboxSweeperRepository(EdiDataPlaneOutboxSweeperRepositoryPort):
    """
    SQLAlchemy implementation for sweeping stranded outbox events.
    """

    def __init__(self, db_router: DatabaseRouter) -> None:
        self.db_router = db_router
        self.sweep_delay_minutes = 5
        self.limit = 500

    async def fetch_stranded_outbox_events(self) -> Sequence[DataPlaneOutbox]:
        """
        Uses a LEFT JOIN to find outbox events older than 5 minutes that have NO matching
        record in the events_processed table.
        """
        threshold = datetime.now(UTC) - timedelta(minutes=self.sweep_delay_minutes)

        # We only sweep events that are strictly expected to be consumed internally.
        # This prevents infinite loops on terminal events like DELIVERY_SUCCESSFUL.
        consumable_events = [
            PipelineEventType.TRANSFORMATION_REQUESTED.value,
            PipelineEventType.COMPUTE_TRANSFORMATION_COMMAND.value,
            PipelineEventType.TRANSFORMATION_SUCCESSFUL.value,
            PipelineEventType.TRANSFORMATION_FAILED.value,
            PipelineEventType.EXECUTE_DELIVERY_COMMAND.value,
            PipelineEventType.DELIVERY_REQUESTED.value,
            PipelineEventType.DELIVERY_SUCCESSFUL.value,
            PipelineEventType.DELIVERY_FAILED.value,
        ]

        stmt = (
            select(DataPlaneOutbox)
            .outerjoin(
                ProcessedEvent,
                and_(
                    DataPlaneOutbox.tenant_id == ProcessedEvent.tenant_id,
                    DataPlaneOutbox.idempotency_key == ProcessedEvent.idempotency_key,
                ),
            )
            .where(
                and_(
                    ProcessedEvent.idempotency_key.is_(None),
                    DataPlaneOutbox.created_at < threshold,
                    DataPlaneOutbox.event_type.in_(consumable_events),
                )
            )
            .order_by(DataPlaneOutbox.created_at.asc())
            .limit(self.limit)
        )

        try:
            shards = await self.db_router.get_all_shards()
            all_events: list[DataPlaneOutbox] = []
            for shard_name, shard_dsn in shards:
                async for session in self.db_router.get_shard_session(shard_name, shard_dsn):
                    result = await session.execute(stmt)
                    all_events.extend(result.scalars().all())
            return all_events
        except Exception:
            logger.exception("failed_to_fetch_stranded_outbox_events")
            raise
