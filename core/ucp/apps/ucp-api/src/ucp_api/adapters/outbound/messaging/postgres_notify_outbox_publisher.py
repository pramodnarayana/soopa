import json
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ucp_models.events import ControlPlaneOutbox


logger = logging.getLogger(__name__)


class PostgresNotifyOutboxPublisher:
    """
    Simulates AWS SNS/SQS in local development by using PostgreSQL LISTEN/NOTIFY.
    The EDI worker listens on the 'control_plane_events' channel.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def publish(self, event: ControlPlaneOutbox) -> None:
        async with self.session_factory() as session:
            # Prefer notifying with just the event ID to avoid payload size limits
            payload_str = json.dumps(
                {
                    "eventId": event.id,
                    "eventType": event.event_type,
                    "tenantId": event.tenant_id,
                }
            )

            # Validate PostgreSQL NOTIFY 8000-byte payload limit
            payload_bytes = payload_str.encode("utf-8")
            if len(payload_bytes) > 8000:
                raise ValueError(
                    f"pg_notify payload exceeds 8000-byte limit: {len(payload_bytes)} bytes"
                )

            # Using pg_notify
            query = text("SELECT pg_notify('control_plane_events', :payload)")
            await session.execute(query, {"payload": payload_str})
            await session.commit()

            logger.info(
                f"Published event {event.event_type} (id: {event.id}) to control_plane_events channel via pg_notify."
            )
