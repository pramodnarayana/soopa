from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from seedwork.models import AggregateRoot

from notification.domain.events import NotificationDispatchedEvent


class Channel(StrEnum):
    EMAIL = "EMAIL"
    IN_APP = "IN_APP"
    SLACK = "SLACK"


@dataclass(frozen=True)
class NotificationEvent:
    tenant_id: str
    event_type: str
    data: Mapping[str, Any] = field(default_factory=dict)


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


@dataclass(frozen=True)
class NotificationPreference:
    id: str
    tenant_id: str
    event_type: str
    channels: tuple[Channel, ...]


@dataclass(frozen=True)
class NotificationOutboxEvent:
    tenant_id: str
    event_type: str
    idempotency_key: str
    payload: Mapping[str, Any]
    id: str | None = None


@dataclass(frozen=True)
class UserNotificationPreference:
    id: str
    tenant_id: str
    user_id: str
    event_type: str
    channel: Channel
    is_enabled: bool


# Platform-level sentinel tenant ID used for global default notification templates.
PLATFORM_TENANT_ID = "ten_000"


@dataclass
class NotificationDispatch(AggregateRoot):
    id: str
    tenant_id: str
    channel: Channel
    subject: str | None
    body: str
    data: dict[str, Any]
    target_user_id: str | None

    @classmethod
    def create(
        cls,
        tenant_id: str,
        channel: Channel,
        subject: str | None,
        body: str,
        data: dict[str, Any],
        idempotency_key: str,
    ) -> "NotificationDispatch":
        dispatch = cls(
            id=idempotency_key,
            tenant_id=tenant_id,
            channel=channel,
            subject=subject,
            body=body,
            data=data,
            target_user_id=data.get("user_id") or data.get("target_user_id"),
        )
        dispatch.add_domain_event(
            NotificationDispatchedEvent(
                tenant_id=tenant_id,
                channel=channel.value,
                subject=subject,
                content=body,
                data=data,
                id=idempotency_key,
            )
        )
        return dispatch
