"""Outbound repository ports for the Transportation Management System (TMS) canonical domain."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from ip.engine.ports.outbound.uow import DomainRepositoryKey
from ip.solutions.domains.tms.canonical import CanonicalCarrierDTO, CanonicalLoadDTO


@runtime_checkable
class TmsDomainRepositoryPort(Protocol):
    """Abstract repository port for persisting and querying TMS canonical tables."""

    async def save_load(self, dto: CanonicalLoadDTO) -> None: ...

    async def list_loads_by_status(
        self,
        tenant_id: str,
        status: str,
        limit: int = 100,
    ) -> Sequence[CanonicalLoadDTO]: ...

    async def save_carrier(self, dto: CanonicalCarrierDTO) -> None: ...

    async def get_carrier_by_scac(
        self,
        tenant_id: str,
        scac_code: str,
    ) -> CanonicalCarrierDTO | None: ...


def _narrow_tms_domain_repository(
    candidate: object,
) -> TmsDomainRepositoryPort | None:
    return candidate if isinstance(candidate, TmsDomainRepositoryPort) else None


TMS_DOMAIN_REPOSITORY_KEY: DomainRepositoryKey[TmsDomainRepositoryPort] = DomainRepositoryKey(
    name="tms",
    narrow=_narrow_tms_domain_repository,
)


__all__ = ["TMS_DOMAIN_REPOSITORY_KEY", "TmsDomainRepositoryPort"]
