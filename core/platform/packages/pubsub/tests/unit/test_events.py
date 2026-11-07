from pubsub.events import EventEnvelope


def test_events_reexports_event_envelope() -> None:
    assert EventEnvelope is not None
