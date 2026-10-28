"""Outbound repository ports for the Energy Smart Grid MDM canonical domain."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ip.application.domains.energy.canonical import (
    CanonicalMeterReadingDTO,
    CanonicalServicePointDTO,
)


class EnergyDomainRepositoryPort(Protocol):
    """Abstract repository port for persisting and querying Energy MDM canonical tables."""

    async def save_meter_reading(self, dto: CanonicalMeterReadingDTO) -> None: ...

    async def list_readings_by_meter(
        self,
        tenant_id: str,
        meter_serial_number: str,
        limit: int = 100,
    ) -> Sequence[CanonicalMeterReadingDTO]: ...

    async def save_service_point(self, dto: CanonicalServicePointDTO) -> None: ...

    async def get_service_point_by_external_id(
        self,
        tenant_id: str,
        service_point_external_id: str,
    ) -> CanonicalServicePointDTO | None: ...

    async def soft_delete_service_point(
        self,
        tenant_id: str,
        service_point_external_id: str,
        trace_id: str,
        correlation_id: str | None = None,
    ) -> None: ...

    async def soft_delete_meter_reading_by_id(
        self,
        tenant_id: str,
        reading_id: str,
        trace_id: str,
        correlation_id: str | None = None,
    ) -> None: ...

    async def update_meter_reading_service_point(
        self,
        tenant_id: str,
        reading_id: str,
        service_point_id: str,
        trace_id: str,
    ) -> None: ...


__all__ = ["EnergyDomainRepositoryPort"]
