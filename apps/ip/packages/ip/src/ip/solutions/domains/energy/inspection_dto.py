"""Domain DTOs for High-Volume Smart Grid AMI Meter Reading Inspection and Search."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field
from seedwork.domain.types import JsonDict

ReadingValue = str | int | float | bool | datetime | None


@dataclass(frozen=True, slots=True)
class MeterReadingSearchFilterDTO:
    """Query filters for high-speed primary key search."""

    tenant_id: str
    meter_serial_number: str | None = None
    service_point_id: str | None = None
    start_time_utc: datetime | None = None
    end_time_utc: datetime | None = None
    quality_status: str | None = None
    correlation_id: str | None = None
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True, slots=True)
class MeterReadingSummaryDTO:
    """Instant summary projection for a single meter device."""

    meter_serial_number: str
    tenant_id: str
    latest_interval_end_utc: datetime | None
    active_quality_status: str
    total_readings_24h: int
    total_kwh_delivered_24h: float
    total_kwh_received_24h: float
    average_voltage_v: float
    last_delivery_receipt_id: str | None


@dataclass(frozen=True, slots=True)
class BatchReadingSampleResponseDTO:
    """Instant 50-row micro-sample data grid projection."""

    batch_id: str
    tenant_id: str
    total_count: int
    valid_count: int
    quarantined_count: int
    window_start_utc: datetime
    window_end_utc: datetime
    micro_sample_records: tuple[JsonDict, ...]


# --- HTTP Boundary DTOs (Pydantic schemas for FastAPI) ---


class MeterReadingSummaryHttpDTO(BaseModel):
    """Summary metrics projection for a queried meter."""

    meter_serial_number: str
    tenant_id: str
    latest_interval_end_utc: datetime | None = None
    active_quality_status: str
    total_readings_24h: int
    total_kwh_delivered_24h: float
    total_kwh_received_24h: float
    average_voltage_v: float
    last_delivery_receipt_id: str | None = None


class MeterReadingSearchHttpResponse(BaseModel):
    """Response payload containing summary and readings matching query."""

    summary: MeterReadingSummaryHttpDTO
    readings: list[dict[str, ReadingValue]] = Field(default_factory=list)


class BatchReadingSampleHttpResponse(BaseModel):
    """50-row micro-sample data grid projection for a batch."""

    batch_id: str
    tenant_id: str
    total_count: int
    valid_count: int
    quarantined_count: int
    window_start_utc: datetime
    window_end_utc: datetime
    micro_sample_records: list[dict[str, ReadingValue]] = Field(default_factory=list)
