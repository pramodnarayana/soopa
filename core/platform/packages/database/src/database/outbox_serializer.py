import dataclasses
import json
from datetime import datetime
from enum import Enum
from uuid import UUID

from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope, EventProcessingLane

from database.models.common import OutboxMixin


class DomainEventEncoder(json.JSONEncoder):
    """JSON Encoder that handles enums, dates, UUIDs, and dataclasses."""

    def default(self, obj: object) -> object:
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, (UUID, datetime)):
            return str(obj)
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return dataclasses.asdict(obj)
        return super().default(obj)


def serialize_domain_event(event: object) -> JsonDict:
    """
    Serializes a pure @dataclass Domain Event into a dictionary suitable for Postgres JSONB columns,
    properly coercing Enums, UUIDs, and Dates into primitive formats.
    """
    result: JsonDict = json.loads(json.dumps(event, cls=DomainEventEncoder))
    return dict(result)


def map_outbox_row_to_envelope(row: OutboxMixin, *, source: str) -> EventEnvelope:
    """Maps a typed SQLAlchemy OutboxMixin ORM row directly to a seedwork EventEnvelope."""
    raw_lane = (
        row.lane if isinstance(row.lane, str) and row.lane else EventProcessingLane.REALTIME.value
    )
    try:
        lane = EventProcessingLane(raw_lane)
    except ValueError:
        lane = EventProcessingLane.REALTIME

    return EventEnvelope(
        id=str(row.id),
        source=source,
        event_type=str(row.event_type),
        tenant_id=str(row.tenant_id) if row.tenant_id else None,
        idempotency_key=str(row.idempotency_key) if row.idempotency_key else None,
        payload=dict(row.payload) if isinstance(row.payload, dict) else {},
        trace_id=str(row.trace_id) if row.trace_id else None,
        correlation_id=str(row.correlation_id) if row.correlation_id else None,
        lane=lane,
    )
