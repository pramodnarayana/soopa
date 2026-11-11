"""Centralized domain-agnostic database shard discovery and override resolution."""

from __future__ import annotations

from collections.abc import Mapping

import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database.provider import DatabaseProvider
from database.utils import normalize_to_asyncpg

logger = structlog.get_logger(__name__)


def collect_prefixed_shard_overrides(
    environ: Mapping[str, str],
    base_overrides: Mapping[str, str],
    *,
    shard_prefix: str,
    default_shard_id: str | None = None,
    default_dsn_env_var: str | None = None,
) -> dict[str, str]:
    """Resolve shard DSN overrides matching ``shard_prefix`` with deterministic precedence.

    Precedence (lowest to highest):
    1. ``base_overrides`` (e.g. ``PlatformDatabaseSettings.shard_overrides``)
    2. ``default_dsn_env_var`` (e.g. ``IP_DATABASE_URL`` -> ``ip_shard_1``)
    3. ``SHARD_OVERRIDES__<SHARD_ID>``
    4. ``DATABASE__SHARD_OVERRIDES__<SHARD_ID>``
    """
    normalized_prefix = shard_prefix.lower()
    resolved: dict[str, str] = {
        shard_id.lower(): normalize_to_asyncpg(dsn.strip())
        for shard_id, dsn in base_overrides.items()
        if shard_id.lower().startswith(normalized_prefix) and dsn.strip()
    }

    if default_shard_id and default_dsn_env_var:
        default_url = environ.get(default_dsn_env_var, "").strip()
        if default_url:
            resolved[default_shard_id.lower()] = normalize_to_asyncpg(default_url)

    for key, val in environ.items():
        stripped = val.strip()
        if not stripped or not key.startswith("SHARD_OVERRIDES__"):
            continue
        shard_id = key.removeprefix("SHARD_OVERRIDES__").lower()
        if shard_id.startswith(normalized_prefix):
            resolved[shard_id] = normalize_to_asyncpg(stripped)

    for key, val in environ.items():
        stripped = val.strip()
        if not stripped or not key.startswith("DATABASE__SHARD_OVERRIDES__"):
            continue
        shard_id = key.removeprefix("DATABASE__SHARD_OVERRIDES__").lower()
        if shard_id.startswith(normalized_prefix):
            resolved[shard_id] = normalize_to_asyncpg(stripped)

    return resolved


async def fetch_prefixed_shard_urls(
    global_url: str,
    overrides: Mapping[str, str],
    *,
    shard_prefix: str,
) -> list[str]:
    """Query ``ucp.database_shards`` for ``shard_prefix`` shards, apply overrides, and deduplicate."""
    normalized_prefix = shard_prefix.lower()
    provider = DatabaseProvider.from_url(normalize_to_asyncpg(global_url))
    shard_map: dict[str, str] = {}
    try:
        async with provider.session() as session:
            result = await session.execute(text("SELECT id, dsn FROM ucp.database_shards"))
            for row in result.fetchall():
                shard_id, dsn = row
                shard_key = str(shard_id).lower()
                raw_dsn = str(dsn).strip()
                if shard_key.startswith(normalized_prefix) and raw_dsn:
                    shard_map[shard_key] = normalize_to_asyncpg(raw_dsn)
    except DBAPIError as err:
        if not overrides:
            logger.error(
                "ucp_database_shards_query_failed_no_overrides",
                shard_prefix=normalized_prefix,
                error=str(err),
            )
            raise
        logger.warning(
            "ucp_database_shards_unavailable_using_overrides",
            shard_prefix=normalized_prefix,
            error=str(err),
        )
    finally:
        await provider.close()

    for shard_id, dsn in overrides.items():
        shard_key = shard_id.lower()
        stripped = dsn.strip()
        if shard_key.startswith(normalized_prefix) and stripped:
            shard_map[shard_key] = normalize_to_asyncpg(stripped)

    return sorted(set(shard_map.values()))
