from sqlalchemy.engine.url import make_url


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
    Normalizes a postgresql+asyncpg URL back to the standard postgresql driver.
    Useful for tools like raw asyncpg.connect() which do not support dialect prefixes.
    """
    if not url:
        return url

    url_obj = make_url(url)
    if url_obj.drivername == "postgresql+asyncpg":
        return url_obj.set(drivername="postgresql").render_as_string(hide_password=False)
    return url


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
