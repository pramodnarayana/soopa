from dataclasses import dataclass

from notification.domain.enums import Channel


@dataclass(frozen=True)
class Template:
    id: str
    tenant_id: str
    name: str
    event_type: str
    channel: Channel
    subject: str | None
    body_content: str
    is_active: bool = True


__all__ = ["Template"]
