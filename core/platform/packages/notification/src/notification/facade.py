from pubsub.events import EventEnvelope
from seedwork.constants import SystemIdPrefix
from seedwork.domain.types import JsonDict
from seedwork.utils import generate_id


def notify(
    tenant_id: str,
    source: str,
    notification_type: str,
    notification_data: JsonDict,
    idempotency_key: str | None = None,
) -> EventEnvelope:
    """
    Creates an Outbox EventEnvelope for requesting a notification.

    This facade should be used by upstream bounded contexts (e.g., EDI, Identity)
    to dispatch notifications asynchronously. The returned event MUST be saved
    to the caller's local outbox repository in the same transaction as their domain changes.
    """
    return EventEnvelope(
        id=generate_id(SystemIdPrefix.GENERIC),
        source=source,
        event_type="notification.requested",
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        payload={
            "notification_type": notification_type,
            "notification_data": notification_data,
        },
    )
