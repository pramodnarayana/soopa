from edi.adapters.outbound.database.transaction_repository import _event_idempotency_key


def test_event_idempotency_key_indexes_generated_base_key() -> None:
    key = _event_idempotency_key(None, index=1, event_count=2)

    base_key, separator, index = key.rpartition("_")
    assert base_key.startswith("sys_")
    assert separator == "_"
    assert index == "1"
    assert not key.startswith("None_")


def test_event_idempotency_key_preserves_explicit_base_key() -> None:
    assert _event_idempotency_key("request-1", index=0, event_count=2) == "request-1_0"
    assert _event_idempotency_key("request-1", index=0, event_count=1) == "request-1"
