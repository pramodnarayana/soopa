from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Channel(StrEnum):
    EMAIL = "EMAIL"
    IN_APP = "IN_APP"
    SLACK = "SLACK"


@dataclass(frozen=True)
class NotificationEvent:
    tenant_id: str
    event_type: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Template:
    id: str
    tenant_id: str
    event_type: str
    channel: Channel
    subject: str | None
    body_content: str
    is_active: bool = True


@dataclass(frozen=True)
class NotificationPreference:
    id: str
    tenant_id: str
    event_type: str
    channels: list[str]


@dataclass(frozen=True)
class NotificationOutboxEvent:
    tenant_id: str
    event_type: str
    idempotency_key: str
    payload: dict[str, Any]
    id: str | None = None
