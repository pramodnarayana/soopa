"""Outbound network security adapter delegating to centralized platform shttp."""

from __future__ import annotations

from shttp.security.ssrf import (
    get_safe_ip,
    is_ip_private_or_restricted,
    ssrf_safe_context,
    validate_target_url,
)

__all__ = [
    "get_safe_ip",
    "is_ip_private_or_restricted",
    "ssrf_safe_context",
    "validate_target_url",
]
