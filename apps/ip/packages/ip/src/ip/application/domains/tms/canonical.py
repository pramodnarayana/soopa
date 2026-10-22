"""Pure Canonical Domain DTOs for Transportation Management System (TMS Loads & Carriers)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CanonicalLoadDTO:
    """Canonical representation of a TMS freight load / shipment."""

    id: str
    tenant_id: str
    trace_id: str
    source_connection_id: str
    source_replica_id: str
    load_reference_number: str
    carrier_scac: str | None
    origin_city: str
    origin_state: str
    destination_city: str
    destination_state: str
    status: str
    total_weight_lbs: float
    freight_charge_usd: float
    pickup_scheduled_at: datetime | None
    delivery_scheduled_at: datetime | None
    updated_at: datetime
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0


@dataclass(frozen=True)
class CanonicalCarrierDTO:
    """Canonical representation of a freight carrier in TMS."""

    id: str
    tenant_id: str
    trace_id: str
    source_connection_id: str
    source_replica_id: str
    scac_code: str
    carrier_name: str
    dot_number: str | None
    mc_number: str | None
    safety_rating: str | None
    status: str
    updated_at: datetime
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0
