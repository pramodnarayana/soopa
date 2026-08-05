from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


class Channel(str, Enum):
    EMAIL = "EMAIL"
    IN_APP = "IN_APP"
    SLACK = "SLACK"


class NotificationEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    event_type: str
    channels: list[Channel]
    data: dict[str, Any]


class Template(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    tenant_id: str
    event_type: str
    channel: Channel
    subject: str | None
    body_content: str
