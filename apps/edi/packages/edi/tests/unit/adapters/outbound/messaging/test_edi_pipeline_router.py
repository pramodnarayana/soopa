import pytest
from seedwork.events import EventEnvelope

from edi.adapters.outbound.pubsub.edi_pipeline_router import (
    EdiPipelineEventRouter,
    UnroutableEventError,
)
from edi.domain.enums import PipelineEventType


class RecordingPublisher:
    """In-memory OutboxPublisherPort that records what it receives."""

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.received: list[EventEnvelope] = []
        self._fail_with = fail_with

    async def publish(self, event: EventEnvelope) -> None:
        if self._fail_with:
            raise self._fail_with
        self.received.append(event)

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        if self._fail_with:
            raise self._fail_with
        self.received.extend(events)
        return [event.id for event in events]


def _event(event_id: str, event_type: PipelineEventType) -> EventEnvelope:
    return EventEnvelope(
        id=event_id,
        source="edi",
        event_type=event_type.value,
        tenant_id="tenant-1",
        idempotency_key=None,
        payload={},
    )


def _router(
    orchestrator: RecordingPublisher, compute: RecordingPublisher
) -> EdiPipelineEventRouter:
    return EdiPipelineEventRouter(
        routes={
            PipelineEventType.TRANSFORMATION_REQUESTED.value: orchestrator,
            PipelineEventType.COMPUTE_TRANSFORMATION_COMMAND.value: compute,
        }
    )


async def test_publish_routes_event_to_its_stage() -> None:
    orchestrator, compute = RecordingPublisher(), RecordingPublisher()
    event = _event("e1", PipelineEventType.COMPUTE_TRANSFORMATION_COMMAND)

    await _router(orchestrator, compute).publish(event)

    assert compute.received == [event]
    assert orchestrator.received == []


async def test_publish_unknown_event_type_raises() -> None:
    router = _router(RecordingPublisher(), RecordingPublisher())

    with pytest.raises(UnroutableEventError):
        await router.publish(_event("e1", PipelineEventType.DELIVERY_FAILED))


async def test_publish_batch_groups_by_destination_and_returns_all_acked_ids() -> None:
    orchestrator, compute = RecordingPublisher(), RecordingPublisher()
    events = [
        _event("e1", PipelineEventType.TRANSFORMATION_REQUESTED),
        _event("e2", PipelineEventType.COMPUTE_TRANSFORMATION_COMMAND),
        _event("e3", PipelineEventType.TRANSFORMATION_REQUESTED),
    ]

    acked = await _router(orchestrator, compute).publish_batch(events)

    assert sorted(acked) == ["e1", "e2", "e3"]
    assert [e.id for e in orchestrator.received] == ["e1", "e3"]
    assert [e.id for e in compute.received] == ["e2"]


async def test_publish_batch_leaves_unroutable_events_unacknowledged() -> None:
    orchestrator, compute = RecordingPublisher(), RecordingPublisher()
    events = [
        _event("e1", PipelineEventType.TRANSFORMATION_REQUESTED),
        _event("e2", PipelineEventType.DELIVERY_FAILED),
    ]

    acked = await _router(orchestrator, compute).publish_batch(events)

    assert acked == ["e1"]


async def test_publish_batch_returns_partial_success_when_one_destination_fails() -> None:
    orchestrator = RecordingPublisher()
    compute = RecordingPublisher(fail_with=RuntimeError("compute queue down"))
    events = [
        _event("e1", PipelineEventType.TRANSFORMATION_REQUESTED),
        _event("e2", PipelineEventType.COMPUTE_TRANSFORMATION_COMMAND),
    ]

    acked = await _router(orchestrator, compute).publish_batch(events)

    assert acked == ["e1"]


async def test_publish_batch_propagates_transport_error_when_nothing_acked() -> None:
    compute = RecordingPublisher(fail_with=RuntimeError("compute queue down"))
    router = _router(RecordingPublisher(), compute)

    with pytest.raises(RuntimeError, match="compute queue down"):
        await router.publish_batch([_event("e1", PipelineEventType.COMPUTE_TRANSFORMATION_COMMAND)])
