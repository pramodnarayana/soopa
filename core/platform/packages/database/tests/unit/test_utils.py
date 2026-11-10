from __future__ import annotations

import pytest

from database.outbox_serializer import deserialize_event_envelope_json
from database.utils import (
    is_postgres_dsn,
    normalize_to_asyncpg,
    normalize_to_standard_postgres,
    pgbouncer_transaction_connect_args,
)


def test_normalize_to_asyncpg() -> None:
    # Test valid standard postgres url
    assert (
        normalize_to_asyncpg("postgresql://user:pass@localhost:5432/db")
        == "postgresql+asyncpg://user:pass@localhost:5432/db"
    )
    assert (
        normalize_to_asyncpg("postgres://user:pass@localhost:5432/db")
        == "postgresql+asyncpg://user:pass@localhost:5432/db"
    )

    # Test already normalized url
    assert (
        normalize_to_asyncpg("postgresql+asyncpg://user:pass@localhost:5432/db")
        == "postgresql+asyncpg://user:pass@localhost:5432/db"
    )

    # Test empty/None string (function takes str but let's test edge cases just in case)
    assert normalize_to_asyncpg("") == ""


def test_normalize_to_standard_postgres() -> None:
    # Test asyncpg and other driver-qualified postgres urls
    assert (
        normalize_to_standard_postgres("postgresql+asyncpg://user:pass@localhost:5432/db")
        == "postgresql://user:pass@localhost:5432/db"
    )
    assert (
        normalize_to_standard_postgres("postgresql+psycopg2://user:pass@localhost:5432/db")
        == "postgresql://user:pass@localhost:5432/db"
    )
    assert (
        normalize_to_standard_postgres("postgres://user:pass@localhost:5432/db")
        == "postgresql://user:pass@localhost:5432/db"
    )

    # Test already standard
    assert (
        normalize_to_standard_postgres("postgresql://user:pass@localhost:5432/db")
        == "postgresql://user:pass@localhost:5432/db"
    )

    # Test empty and non-postgres string
    assert normalize_to_standard_postgres("") == ""
    assert normalize_to_standard_postgres("sqlite+aiosqlite:///:memory:") == (
        "sqlite+aiosqlite:///:memory:"
    )


def test_is_postgres_dsn() -> None:
    assert is_postgres_dsn("postgresql://user:pass@localhost:5432/db") is True
    assert is_postgres_dsn("postgresql+psycopg2://user:pass@localhost:5432/db") is True
    assert is_postgres_dsn("postgres+asyncpg://user:pass@localhost:5432/db") is True
    assert is_postgres_dsn("sqlite+aiosqlite:///:memory:") is False
    assert is_postgres_dsn("zitadel") is False
    assert is_postgres_dsn("") is False


def test_deserialize_event_envelope_json_normalizes_syntax_error() -> None:
    with pytest.raises(ValueError, match="Malformed JSON string for EventEnvelope"):
        deserialize_event_envelope_json("invalid-json{")


def test_deserialize_event_envelope_json_normalizes_non_object() -> None:
    with pytest.raises(ValueError, match="Serialized EventEnvelope root must be a JSON object"):
        deserialize_event_envelope_json('["not", "an", "object"]')


def test_deserialize_event_envelope_json_normalizes_missing_required_keys() -> None:
    with pytest.raises(ValueError, match="Missing required EventEnvelope fields: id, source"):
        deserialize_event_envelope_json('{"event_type": "test.event"}')


def test_pgbouncer_transaction_connect_args_disables_statement_cache() -> None:
    args = pgbouncer_transaction_connect_args()
    assert args["statement_cache_size"] == 0
    assert args["server_settings"] == {"search_path": "public"}
