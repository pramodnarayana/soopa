"""Segregated Write and Read Session Routing Ports for Shard-Routed Providers."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Protocol, TypeVar, runtime_checkable

TSession_co = TypeVar("TSession_co", covariant=True)


@runtime_checkable
class TenantWriteSessionRouterPort(Protocol[TSession_co]):
    """Port yielding a Primary Writer session scoped to `tenant_id` on the resolved shard."""

    def get_tenant_session(
        self,
        tenant_id: str,
        shard_key: str,
        shard_url: str,
    ) -> AsyncGenerator[TSession_co, None]: ...


@runtime_checkable
class TenantReadSessionRouterPort(Protocol[TSession_co]):
    """Segregated CQRS Read Port yielding a read-only session bound to a Read Replica pool."""

    def get_tenant_read_session(
        self,
        tenant_id: str,
        pool_key: str,
        target_dsn: str,
    ) -> AsyncGenerator[TSession_co, None]: ...


__all__ = [
    "TenantReadSessionRouterPort",
    "TenantWriteSessionRouterPort",
]
