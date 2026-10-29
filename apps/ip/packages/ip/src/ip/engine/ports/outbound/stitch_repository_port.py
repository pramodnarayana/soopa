"""Outbound repository port for Stitch persistence in the Control Plane."""

from __future__ import annotations

from typing import Protocol

from ip.engine.domain.stitch import Stitch


class StitchRepositoryPort(Protocol):
    """Port for persisting and querying Stitch records in the Control Plane (`ip.stitches`)."""

    async def save(self, stitch: Stitch) -> None:
        """Upserts a Stitch record."""
        ...

    async def get_by_id(
        self,
        *,
        tenant_id: str,
        stitch_id: str,
    ) -> Stitch | None:
        """Retrieves a Stitch by ID for a tenant (or wildcard '*')."""
        ...

    async def get_by_id_global(
        self,
        *,
        stitch_id: str,
    ) -> Stitch | None:
        """Retrieves a Stitch by ID across all tenants for cross-tenant collision detection."""
        ...

    async def list_by_tenant(
        self,
        *,
        tenant_id: str,
    ) -> list[Stitch]:
        """Lists all Stitches visible to a tenant (tenant-specific and wildcard '*')."""
        ...

    async def list_for_event(
        self,
        *,
        tenant_id: str,
        canonical_event_type: str,
    ) -> list[Stitch]:
        """Lists all active Stitches matching a tenant (or '*') and canonical_event_type."""
        ...


__all__ = ["StitchRepositoryPort"]
