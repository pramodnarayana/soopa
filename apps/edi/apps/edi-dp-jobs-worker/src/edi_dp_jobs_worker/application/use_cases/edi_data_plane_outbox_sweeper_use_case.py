from typing import cast

import structlog
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope

from edi_dp_jobs_worker.ports.outbound.edi_data_plane_outbox_sweeper_repository_port import (
    EdiDataPlaneOutboxSweeperRepositoryPort,
)

logger = structlog.get_logger(__name__)


class EdiDataPlaneOutboxSweeperUseCase:
    """
    Use case to fetch stranded data plane outbox events (events that were never processed
    by the consumer) and republish them to the SQS Events Queue.
    """

    def __init__(
        self,
        repository: EdiDataPlaneOutboxSweeperRepositoryPort,
        publisher: OutboxPublisherPort,
    ) -> None:
        self.repository = repository
        self.publisher = publisher

    async def execute(self) -> None:
        logger.info("edi_data_plane_outbox_sweeper_use_case.started")
        try:
            stranded_events = await self.repository.fetch_stranded_outbox_events()
            if not stranded_events:
                logger.debug("edi_data_plane_outbox_sweeper.no_stranded_events_found")
                return

            logger.info(
                "edi_data_plane_outbox_sweeper.stranded_events_found",
                count=len(stranded_events),
            )

            exceptions = []
            for event in stranded_events:
                # The event.payload is already a serialized JSON dictionary from the outbox table.
                # We can publish it directly.
                try:
                    envelope = EventEnvelope(
                        id=event.id,
                        source="edi",
                        event_type=event.event_type,
                        tenant_id=event.tenant_id,
                        idempotency_key=event.idempotency_key,
                        payload=cast(JsonDict, event.payload),
                    )
                    await self.publisher.publish(envelope)
                    logger.info(
                        "edi_data_plane_outbox_sweeper.event_republished",
                        event_id=event.id,
                        idempotency_key=event.idempotency_key,
                        event_type=event.event_type,
                    )
                except Exception as e:
                    logger.exception(
                        "edi_data_plane_outbox_sweeper.failed_to_republish_event",
                        event_id=event.id,
                    )
                    exceptions.append(e)

            if exceptions:
                logger.error(
                    "edi_data_plane_outbox_sweeper_use_case_completed_with_errors",
                    error_count=len(exceptions),
                )
                raise ExceptionGroup("sweeper_had_failures", exceptions)

            logger.info("edi_data_plane_outbox_sweeper_use_case.completed")
        except Exception:
            logger.exception("edi_data_plane_outbox_sweeper_use_case.failed")
            raise
