from database.utils import is_postgres_dsn, normalize_to_asyncpg, normalize_to_standard_postgres


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
