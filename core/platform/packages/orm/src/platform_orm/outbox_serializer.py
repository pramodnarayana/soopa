import dataclasses
import json
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID


class DomainEventEncoder(json.JSONEncoder):
    """JSON Encoder that can handle enums, dates, UUIDs, and Dataclasses."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, (UUID, datetime)):
            return str(obj)
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return dataclasses.asdict(obj)
        return super().default(obj)


def serialize_domain_event(event: Any) -> dict[str, Any]:
    """
    Serializes a pure @dataclass Domain Event into a dictionary suitable for Postgres JSONB columns,
    properly coercing Enums, UUIDs, and Dates into primitive formats.
    """
    # Uses our custom JSONEncoder to cast Dataclasses, UUIDs, Enums into strings/dicts,
    # and then json.loads it back into a primitive dict which SQLAlchemy needs for a JSONB insert.
    result = json.loads(json.dumps(event, cls=DomainEventEncoder))
    return dict(result)
