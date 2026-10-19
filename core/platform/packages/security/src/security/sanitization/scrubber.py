"""Sanitization utilities for scrubbing sensitive credentials and tokens from logs."""

import re

_URL_AUTH_REGEX = re.compile(r"//[^@\s]+@")
_BEARER_REGEX = re.compile(r"Bearer\s+([A-Za-z0-9_\-\.]+)", re.IGNORECASE)
_BASIC_REGEX = re.compile(r"Basic\s+([A-Za-z0-9+/=]+)", re.IGNORECASE)


def sanitize_error(err: Exception | str, max_length: int = 500) -> str:
    """Returns a log-safe version of an error message with stripped credentials.

    - Strips URL embedded credentials: https://user:pass@host -> https://[REDACTED]@host
    - Masks Bearer and Basic tokens
    - Truncates to max_length
    """
    msg = str(err)
    stripped = _URL_AUTH_REGEX.sub("//[REDACTED]@", msg)
    stripped = _BEARER_REGEX.sub("Bearer [REDACTED]", stripped)
    stripped = _BASIC_REGEX.sub("Basic [REDACTED]", stripped)
    if len(stripped) > max_length:
        return f"{stripped[:max_length]}…"
    return stripped
