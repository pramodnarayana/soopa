"""Outbound repository port for indexed ReBAC resource grants (`identity.resource_grants`)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from identity.domain.dtos import ResourceGrantDTO


class ResourceGrantRepositoryPort(Protocol):
    """Manages fine-grained resource-level collaborative sharing grants (O(log N) at 100M+ rows)."""

    async def find_matching_grants(
        self,
        *,
        tenant_id: str,
        resource_type: str,
        resource_id: str,
        user_id: str,
        role_ids: Sequence[str],
    ) -> tuple[ResourceGrantDTO, ...]: ...

    async def save_grant(self, grant: ResourceGrantDTO) -> ResourceGrantDTO: ...

    async def revoke_grant(self, *, tenant_id: str, grant_id: str) -> bool: ...

    async def list_grants_for_resource(
        self,
        *,
        tenant_id: str,
        resource_type: str,
        resource_id: str,
    ) -> tuple[ResourceGrantDTO, ...]: ...


__all__ = ["ResourceGrantRepositoryPort"]
