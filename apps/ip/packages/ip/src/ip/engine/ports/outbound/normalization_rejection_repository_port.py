"""NormalizationRejectionRepositoryPort for recording L3 mapping and validation rejections."""

from __future__ import annotations

from typing import Protocol

from ip.engine.domain.normalization import (
    NormalizationRejectionEntry,
    NormalizationShadowDiffEntry,
)


class NormalizationRejectionRepositoryPort(Protocol):
    """Port for recording normalization rejections and shadow mode diffs on tenant shards."""

    async def record_rejection(self, rejection: NormalizationRejectionEntry) -> None:
        """Persist a normalization rejection entry."""
        ...

    async def record_shadow_diff(self, diff: NormalizationShadowDiffEntry) -> None:
        """Persist a candidate mapper difference entry in shadow mode."""
        ...
