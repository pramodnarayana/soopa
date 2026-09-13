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
