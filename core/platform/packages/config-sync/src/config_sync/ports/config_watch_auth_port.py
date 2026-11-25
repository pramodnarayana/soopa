"""Inbound Authentication Strategy Port for internal Dynamic Watch HTTP/SSE endpoints."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from seedwork.domain.exceptions import Result

from config_sync.domain.dtos import ConfigSyncError


@runtime_checkable
class ConfigWatchAuthStrategyPort(Protocol):
    """Polymorphic authentication policy for `/api/v1/internal/{app_id}/config/*` endpoints."""

    def verify(self, authorization: str | None) -> Result[None, ConfigSyncError]:
        """Validates the inbound `Authorization` header, returning a structured Result."""
        ...


__all__ = ["ConfigWatchAuthStrategyPort"]
