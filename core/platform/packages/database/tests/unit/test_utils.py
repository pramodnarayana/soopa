from database.utils import normalize_to_asyncpg, normalize_to_standard_postgres


def test_normalize_to_asyncpg():
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


def test_normalize_to_standard_postgres():
    # Test asyncpg url
    assert (
        normalize_to_standard_postgres("postgresql+asyncpg://user:pass@localhost:5432/db")
        == "postgresql://user:pass@localhost:5432/db"
    )

    # Test already standard
    assert (
        normalize_to_standard_postgres("postgresql://user:pass@localhost:5432/db")
        == "postgresql://user:pass@localhost:5432/db"
    )

    # Test empty string
    assert normalize_to_standard_postgres("") == ""
