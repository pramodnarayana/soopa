"""Strongly-typed constants and atomic Lua scripts for `cache.domain`."""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class CacheLookupStatus(StrEnum):
    """First-class outcome status for projection cache reads."""

    HIT_FRESH = "hit_fresh"
    HIT_STALE_REVALIDATE = "hit_stale_revalidate"
    MISS = "miss"
    STORE_ERROR = "store_error"


class CacheUpsertStatus(StrEnum):
    """First-class outcome status for monotonic Compare-And-Set projection writes."""

    APPLIED = "applied"
    SKIPPED_STALE_WATERMARK = "skipped_stale_watermark"
    STORE_ERROR = "store_error"


class CacheStoreOperationStatus(StrEnum):
    """Low-level wire operation outcome without raising exceptions for transient misses."""

    OK = "ok"
    UNAVAILABLE = "unavailable"


# Atomic Compare-And-Set script preventing stale replica reads or out-of-order workers
# from overwriting a projection stamped with a higher causal replication watermark.
UPSERT_IF_NEWER_WATERMARK_LUA: Final[str] = """
local current_wm = redis.call('HGET', KEYS[1], 'watermark')
if (not current_wm) or (tonumber(ARGV[1]) > tonumber(current_wm)) then
    redis.call('HSET', KEYS[1], 'watermark', ARGV[1], 'payload', ARGV[2], 'soft_exp_ms', ARGV[3])
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]))
    return 1
end
return 0
""".strip()

HASH_FIELD_WATERMARK: Final[str] = "watermark"
HASH_FIELD_PAYLOAD: Final[str] = "payload"
HASH_FIELD_SOFT_EXP_MS: Final[str] = "soft_exp_ms"
