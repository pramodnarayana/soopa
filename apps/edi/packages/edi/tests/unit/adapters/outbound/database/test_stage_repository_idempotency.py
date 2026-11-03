from edi.adapters.outbound.database.data_plane.stage_repository_base import (
    event_idempotency_key,
)


def test_event_idempotency_key_indexes_generated_base_key() -> None:
    key = event_idempotency_key(None, index=1, event_count=2)

    base_key, separator, index = key.rpartition("_")
    assert base_key.startswith("sys_")
    assert separator == "_"
    assert index == "1"
    assert not key.startswith("None_")


def test_event_idempotency_key_preserves_explicit_base_key() -> None:
    assert event_idempotency_key("request-1", index=0, event_count=2) == "request-1_0"
    assert event_idempotency_key("request-1", index=0, event_count=1) == "request-1"
