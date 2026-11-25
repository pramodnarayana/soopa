from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from pubsub.adapters.database.sqlalchemy_database_queue_repository import SessionScopeFactory
from pubsub.provider import PubSubProvider

from edi.adapters.outbound.pubsub.edi_pipeline_router import EdiPipelineEventRouter
from edi.domain.transaction.enums import PipelineEventType

EDI_ORCHESTRATOR_EVENT_TYPES: tuple[str, ...] = (
    PipelineEventType.TRANSFORMATION_REQUESTED.value,
    PipelineEventType.TRANSFORMATION_SUCCESSFUL.value,
    PipelineEventType.TRANSFORMATION_FAILED.value,
    PipelineEventType.DELIVERY_REQUESTED.value,
    PipelineEventType.DELIVERY_SUCCESSFUL.value,
    PipelineEventType.DELIVERY_FAILED.value,
)

EDI_COMPUTE_EVENT_TYPES: tuple[str, ...] = (PipelineEventType.COMPUTE_TRANSFORMATION_COMMAND.value,)

EDI_DELIVERY_EVENT_TYPES: tuple[str, ...] = (PipelineEventType.EXECUTE_DELIVERY_COMMAND.value,)


def create_edi_pipeline_publisher(
    compute_queue_url: str,
    orchestrator_queue_url: str,
    deliver_queue_url: str,
    region_name: str,
    endpoint_url: str | None = None,
    database_url: str | None = None,
    session_factory: SessionScopeFactory | None = None,
) -> OutboxPublisherPort:
    """
    Single source of truth for the EDI pipeline routing table.

    Maps each PipelineEventType to the stage that consumes it and wires an
    EdiPipelineEventRouter over one dumb publisher per destination. Every worker
    container uses this factory so routing can never diverge between processes.
    """

    def publisher_for(queue_url: str) -> OutboxPublisherPort:
        return PubSubProvider.create_outbox_publisher(
            destination_uri=queue_url,
            region_name=region_name,
            endpoint_url=endpoint_url,
            session_factory=session_factory,
            database_url=database_url,
        )

    orchestrator = publisher_for(orchestrator_queue_url)
    compute = publisher_for(compute_queue_url)
    deliver = publisher_for(deliver_queue_url)

    return EdiPipelineEventRouter(
        routes={
            PipelineEventType.TRANSFORMATION_REQUESTED.value: orchestrator,
            PipelineEventType.COMPUTE_TRANSFORMATION_COMMAND.value: compute,
            PipelineEventType.TRANSFORMATION_SUCCESSFUL.value: orchestrator,
            PipelineEventType.TRANSFORMATION_FAILED.value: orchestrator,
            PipelineEventType.DELIVERY_REQUESTED.value: orchestrator,
            PipelineEventType.EXECUTE_DELIVERY_COMMAND.value: deliver,
            PipelineEventType.DELIVERY_SUCCESSFUL.value: orchestrator,
            PipelineEventType.DELIVERY_FAILED.value: orchestrator,
        }
    )
