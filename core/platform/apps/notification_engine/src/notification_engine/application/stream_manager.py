import asyncio
import logging
from collections import defaultdict

from notification_engine.application.ports.notification_query_port import NotificationDTO
from notification_engine.application.ports.notification_stream_port import NotificationStreamPort

logger = logging.getLogger(__name__)


class NotificationStreamManager(NotificationStreamPort):
    """
    Singleton manager that holds connected Server-Sent Events (SSE) queues
    for active Web UI clients.
    """

    def __init__(self) -> None:
        # Maps (tenant_id, user_id) -> set of asyncio.Queue
        self._queues: dict[tuple[str, str], set[asyncio.Queue[NotificationDTO]]] = defaultdict(set)

    def subscribe(self, tenant_id: str, user_id: str) -> asyncio.Queue[NotificationDTO]:
        """Creates a new queue for a client connection and registers it."""
        queue: asyncio.Queue[NotificationDTO] = asyncio.Queue()
        self._queues[(tenant_id, user_id)].add(queue)
        logger.debug(f"Subscribed SSE client for tenant={tenant_id}, user={user_id}")
        return queue

    def unsubscribe(
        self, tenant_id: str, user_id: str, queue: asyncio.Queue[NotificationDTO]
    ) -> None:
        """Removes a client's queue when they disconnect."""
        key = (tenant_id, user_id)
        if key in self._queues:
            if queue in self._queues[key]:
                self._queues[key].remove(queue)
            if not self._queues[key]:
                del self._queues[key]
        logger.debug(f"Unsubscribed SSE client for tenant={tenant_id}, user={user_id}")

    async def broadcast(self, tenant_id: str, user_id: str, notification: NotificationDTO) -> None:
        """Pushes a notification to all connected queues for a specific user."""
        key = (tenant_id, user_id)
        if key in self._queues:
            queues_to_notify = self._queues[key]
            logger.debug(
                f"Broadcasting notification to {len(queues_to_notify)} client(s) for user={user_id}"
            )
            for queue in queues_to_notify:
                await queue.put(notification)
