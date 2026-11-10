"""Domain Exceptions for Multi-Tenant & Cellular Sharding."""

from __future__ import annotations


class ShardingInfrastructureError(Exception):
    """Base exception for sharding and pod resolution operations."""


class TenantNotFoundError(ShardingInfrastructureError, ValueError):
    """Raised by legacy exception-based callers when a tenant is unmapped in the shard registry."""


__all__ = [
    "ShardingInfrastructureError",
    "TenantNotFoundError",
]
