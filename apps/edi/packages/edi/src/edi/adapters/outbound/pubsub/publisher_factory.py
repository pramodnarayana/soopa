from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from pubsub.provider import PubSubProvider

from edi.adapters.outbound.pubsub.edi_pipeline_router import EdiPipelineEventRouter
from edi.domain.enums import PipelineEventType


def create_edi_pipeline_publisher(
    compute_queue_url: str,
    orchestrator_queue_url: str,
    deliver_queue_url: str,
    region_name: str,
    endpoint_url: str | None = None,
) -> OutboxPublisherPort:
    """
    Single source of truth for the EDI pipeline routing table.

    Maps each PipelineEventType to the stage that consumes it and wires an
    EdiPipelineEventRouter over one dumb publisher per destination. Every worker
    container uses this factory so routing can never diverge between processes.
    """

    def publisher_for(queue_url: str) -> OutboxPublisherPort:
        return PubSubProvider.create_queue_publisher(
            queue_url=queue_url,
            region_name=region_name,
            endpoint_url=endpoint_url,
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
