import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from database.connection import DatabaseRouter
from database.models.control_plane import ControlPlaneOutbox
from domain.events import ProvisioningEventType
from sqlalchemy import select

from worker.core.errors import PermanentProvisioningError
from worker.ports.outbox import OutboxEvent, OutboxPort

logger = logging.getLogger(__name__)


class SqlAlchemyOutboxAdapter(OutboxPort):
    def __init__(self, db_router: DatabaseRouter):
        self.db_router = db_router

    @asynccontextmanager
    async def process_next_event(self) -> AsyncIterator[OutboxEvent | None]:
        global_gen = self.db_router.get_global_session()
        global_session = await global_gen.__anext__()

        try:
            stmt = (
                select(ControlPlaneOutbox)
                .where(
                    ControlPlaneOutbox.status == "PENDING",
                    ControlPlaneOutbox.event_type.in_(list(ProvisioningEventType)),
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            result = await global_session.execute(stmt)
            event = result.scalar_one_or_none()

            if not event:
                yield None
                return

            try:
                yield event
                event.status = "PROCESSED"
                await global_session.commit()
            except Exception as e:
                if isinstance(e, PermanentProvisioningError):
                    logger.error(
                        f"Permanent error processing event {event.id}: {e}. Marking as FAILED."
                    )
                    event.status = "FAILED"
                    await global_session.commit()
                else:
                    logger.exception(
                        f"Transient error processing event {event.id}: {e}. Leaving as PENDING."
                    )
                    await global_session.rollback()
        finally:
            with contextlib.suppress(StopAsyncIteration):
                await global_gen.__anext__()

    async def publish_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        tenant_id: str,
    ) -> None:
        """
        Publishes an event to the global outbox table.
        This writes to ControlPlaneOutbox.
        """
        global_gen = self.db_router.get_global_session()
        global_session = await global_gen.__anext__()
        try:
            new_event = ControlPlaneOutbox(
                event_type=event_type,
                payload=payload,
                idempotency_key=idempotency_key,
                tenant_id=tenant_id,
                status="PENDING",
            )
            global_session.add(new_event)
            await global_session.commit()
            logger.info(f"Published control plane outbox event {event_type} for tenant {tenant_id}")
        except Exception:
            await global_session.rollback()
            raise
        finally:
            with contextlib.suppress(StopAsyncIteration):
                await global_gen.__anext__()
