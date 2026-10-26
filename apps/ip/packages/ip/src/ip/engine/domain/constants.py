"""
IP Domain Constants
===================

Non-enumeration constants, defaults, and sentinels for the Integration Platform bounded context.
All StrEnum definitions live in ``ip.engine.domain.enums``.
"""

from typing import Final

__all__ = [
    "DEFAULT_IDEMPOTENCY_HEADER",
    "DEFAULT_INLINE_THRESHOLD_BYTES",
    "DEFAULT_TOKEN_REFRESH_BUFFER_SECONDS",
    "MAX_RETRY_AFTER_SECONDS",
    "REDACTED_SECRET_VALUE",
    "RESERVED_RAW_BYTES_KEY",
    "SENSITIVE_HTTP_HEADERS",
    "WRAPPED_SCALAR_KEY",
]

# ── Storage & Payload Inlining Constants ─────────────────────────────────────
# Payloads below this threshold are inlined into PostgreSQL JSONB; larger payloads offload to S3.
DEFAULT_INLINE_THRESHOLD_BYTES: Final[int] = 64 * 1024  # 64 KB
RESERVED_RAW_BYTES_KEY: Final[str] = "__raw_payload_b64__"
WRAPPED_SCALAR_KEY: Final[str] = "__wrapped_scalar__"

# ── Layer 5 Outbound Security, Idempotency & Token Refresh Constants ─────────
DEFAULT_IDEMPOTENCY_HEADER: Final[str] = "Idempotency-Key"
DEFAULT_TOKEN_REFRESH_BUFFER_SECONDS: Final[int] = 900  # 15 minutes proactive refresh window
MAX_RETRY_AFTER_SECONDS: Final[int] = 3600  # Cap Retry-After delay to 1 hour
REDACTED_SECRET_VALUE: Final[str] = "***REDACTED***"  # noqa: S105 - Redaction mask sentinel, not a secret credential
SENSITIVE_HTTP_HEADERS: Final[frozenset[str]] = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "cookie",
        "set-cookie",
        "x-auth-token",
    }
)
