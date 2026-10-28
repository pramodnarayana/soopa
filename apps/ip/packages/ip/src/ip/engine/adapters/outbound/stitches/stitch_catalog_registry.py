"""In-memory adapter implementing StitchCatalogRegistryPort."""

from __future__ import annotations

from collections.abc import Sequence

from ip.engine.domain.stitch import Stitch
from ip.engine.ports.outbound.stitch_catalog_registry_port import (
    StitchCatalogRegistryPort,
)


class InMemoryStitchCatalogRegistry(StitchCatalogRegistryPort):
    """Stores Stitches keyed by `(tenant_id, canonical_event_type)`."""

    def __init__(self) -> None:
        self._stitches: list[Stitch] = []

    def register_stitch(self, stitch: Stitch) -> None:
        self._stitches = [
            s for s in self._stitches
            if not (s.id == stitch.id and s.tenant_id == stitch.tenant_id)
        ]
        self._stitches.append(stitch)

    def list_stitches_for_event(
        self,
        *,
        tenant_id: str,
        canonical_event_type: str,
    ) -> Sequence[Stitch]:
        return tuple(
            s
            for s in self._stitches
            if s.tenant_id in (tenant_id, "*")
            and s.canonical_event_type == canonical_event_type
            and s.is_active
        )

    def list_stitches(
        self,
        *,
        tenant_id: str,
    ) -> Sequence[Stitch]:
        return tuple(s for s in self._stitches if s.tenant_id in (tenant_id, "*"))

    def get_stitch(
        self,
        *,
        tenant_id: str,
        stitch_id: str,
    ) -> Stitch | None:
        # Prioritize exact tenant match before wildcard fallback
        for stitch in self._stitches:
            if stitch.id == stitch_id and stitch.tenant_id == tenant_id:
                return stitch
        for stitch in self._stitches:
            if stitch.id == stitch_id and stitch.tenant_id == "*":
                return stitch
        return None

    def find_any_stitch_by_id(
        self,
        *,
        stitch_id: str,
    ) -> Stitch | None:
        for stitch in self._stitches:
            if stitch.id == stitch_id:
                return stitch
        return None


__all__ = ["InMemoryStitchCatalogRegistry"]
