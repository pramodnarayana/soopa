"""Command DTOs for SAP IS-U OData mutations."""

from __future__ import annotations

from dataclasses import dataclass

from seedwork.domain.types import JsonDict


@dataclass(frozen=True, kw_only=True)
class CreateServiceOrderCommand:
    """Co-located Command DTO for creating an SAP IS-U service order."""

    service_point_id: str
    meter_serial_number: str
    scheduled_date: str
    order_type: str = "PM01"
    reason: str = "Field Investigation"

    @classmethod
    def from_payload(cls, payload: JsonDict) -> CreateServiceOrderCommand:
        return cls(
            service_point_id=str(payload["service_point_id"]),
            meter_serial_number=str(payload["meter_serial_number"]),
            scheduled_date=str(payload["scheduled_date"]),
            order_type=str(payload.get("order_type", "PM01")),
            reason=str(payload.get("reason", "Field Investigation")),
        )
