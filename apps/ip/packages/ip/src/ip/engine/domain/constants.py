"""
IP Domain Constants
===================

Non-enumeration constants, defaults, and sentinels for the Integration Platform bounded context.
All StrEnum definitions live in ``ip.engine.domain.enums``.
"""

from typing import Final

__all__ = [
    "DEFAULT_INLINE_THRESHOLD_BYTES",
    "RESERVED_RAW_BYTES_KEY",
    "WRAPPED_SCALAR_KEY",
]

# ── Storage & Payload Inlining Constants ─────────────────────────────────────
# Payloads below this threshold are inlined into PostgreSQL JSONB; larger payloads offload to S3.
DEFAULT_INLINE_THRESHOLD_BYTES: Final[int] = 64 * 1024  # 64 KB
RESERVED_RAW_BYTES_KEY: Final[str] = "__raw_payload_b64__"
WRAPPED_SCALAR_KEY: Final[str] = "__wrapped_scalar__"
