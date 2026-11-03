from dataclasses import dataclass

from seedwork.domain.aggregate import AggregateRoot
from seedwork.domain.types import JsonDict

from notification.domain.enums import Channel
from notification.domain.events import NotificationDispatchedEvent


@dataclass
class NotificationDispatch(AggregateRoot):
    id: str
    tenant_id: str
    channel: Channel
    subject: str | None
    body: str
    data: JsonDict
    target_user_id: str | None

    @classmethod
    def create(
        cls,
        tenant_id: str,
        channel: Channel,
        subject: str | None,
        body: str,
        data: JsonDict,
        idempotency_key: str,
    ) -> "NotificationDispatch":
        target_user_id = data.get("user_id") or data.get("target_user_id")
        dispatch = cls(
            id=idempotency_key,
            tenant_id=tenant_id,
            channel=channel,
            subject=subject,
            body=body,
            data=data,
            target_user_id=str(target_user_id) if target_user_id else None,
        )
        dispatch.add_domain_event(
            NotificationDispatchedEvent(
                tenant_id=tenant_id,
                channel=channel.value,
                subject=subject,
                content=body,
                data=data,
                id=idempotency_key,
                idempotency_key=idempotency_key,
            )
        )
        return dispatch


__all__ = ["NotificationDispatch"]
