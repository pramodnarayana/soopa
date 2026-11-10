from typing import Final

import asyncpg
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

DEFAULT_TEST_DB_SUFFIX: Final[str] = "_test"
MAINTENANCE_DATABASE_NAME: Final[str] = "postgres"
DATABASE_CONNECTION_ERRORS: Final[tuple[type[Exception], ...]] = (
    SQLAlchemyError,
    asyncpg.PostgresError,
    OSError,
    TimeoutError,
)


def is_postgres_dsn(url: str) -> bool:
    """Return True when ``url`` is a SQLAlchemy/PostgreSQL DSN (including driver-qualified URLs)."""
    stripped = url.strip()
    if not stripped:
        return False
    try:
        url_obj = make_url(stripped)
    except ArgumentError:
        return False
    driver = url_obj.drivername
    return driver in ("postgres", "postgresql") or driver.startswith(("postgresql+", "postgres+"))


def normalize_to_asyncpg(url: str) -> str:
    """
    Normalizes a standard postgresql URL to use the asyncpg driver natively.
    Ensures that infrastructure connection string logic is strictly centralized.
    """
    if not url:
        return url

    url_obj = make_url(url)
    if url_obj.drivername in ("postgres", "postgresql"):
        return url_obj.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)
    return url


def normalize_to_standard_postgres(url: str) -> str:
    """
    Normalizes any PostgreSQL dialect/driver URL back to the standard postgresql driver.
    Useful for tools like raw asyncpg.connect() which do not support dialect prefixes.
    """
    if not url or not is_postgres_dsn(url):
        return url

    url_obj = make_url(url)
    if url_obj.drivername != "postgresql":
        return url_obj.set(drivername="postgresql").render_as_string(hide_password=False)
    return url


def extract_database_name(url: str) -> str:
    """Extract the logical database name from a SQLAlchemy/PostgreSQL DSN."""
    if not url:
        return ""
    url_obj = make_url(url)
    return (url_obj.database or "").strip("/")


def rewrite_dsn_to_test_db(url: str, suffix: str = DEFAULT_TEST_DB_SUFFIX) -> str:
    """Rewrite a PostgreSQL DSN so its database name targets an isolated ``*_test`` DB.

    Idempotent if the DSN already targets a ``*_test`` database or ``test``,
    leaves non-PostgreSQL URLs untouched, and rejects PostgreSQL DSNs missing a
    database name.
    """
    if not url or not is_postgres_dsn(url):
        return url

    url_obj = make_url(url)
    db_name = (url_obj.database or "").strip("/")
    if not db_name:
        redacted = url_obj.render_as_string(hide_password=True)
        raise ValueError(f"PostgreSQL DSN is missing a database name: {redacted}")
    if db_name == "test" or db_name.endswith(suffix):
        return url

    return url_obj.set(database=f"{db_name}{suffix}").render_as_string(hide_password=False)


def build_maintenance_dsn(url: str, maintenance_db: str = MAINTENANCE_DATABASE_NAME) -> str:
    """Build a standard synchronous PostgreSQL maintenance DSN (default ``postgres``) for admin DDL."""
    if not url:
        return url

    url_obj = make_url(url)
    driver = "postgresql" if is_postgres_dsn(url) else url_obj.drivername
    return url_obj.set(drivername=driver, database=maintenance_db).render_as_string(
        hide_password=False
    )


def shard_connect_args() -> dict[str, dict[str, str]]:
    """
    Returns the asyncpg connect_args required for all dedicated tenant shard connections.

    Enforces search_path=public explicitly so PostgreSQL never resolves tables via
    the implicit "$user" schema (e.g., creating tables in the "edi" schema when
    connecting as the "edi" user). This is the enterprise-grade pattern for shard
    databases where the DB instance itself is the boundary — not a named schema.

    Usage:
        create_async_engine(url, connect_args=shard_connect_args())
        get_async_engine(url, server_settings=shard_connect_args()["server_settings"])
    """
    return {"server_settings": {"search_path": "public"}}


def pgbouncer_transaction_connect_args() -> dict[str, int | dict[str, str]]:
    """
    Returns asyncpg `connect_args` safe for PgBouncer `pool_mode = transaction`.

    Disables `asyncpg` client-side prepared statement caching (`statement_cache_size=0`)
    so rotating backend PostgreSQL server sessions never raise
    `DuplicatePreparedStatementError` or `InvalidSQLStatementNameError`.
    """
    return {
        "statement_cache_size": 0,
        "server_settings": {"search_path": "public"},
    }
