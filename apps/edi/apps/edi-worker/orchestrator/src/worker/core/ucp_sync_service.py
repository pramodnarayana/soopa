import logging
from collections.abc import Awaitable, Callable
from typing import Any

from worker.ports.api_token import ApiTokenPort
from worker.ports.outbox import OutboxPort
from worker.ports.tenant import TenantPort
from worker.ports.ucp_event_listener import UcpEventListenerPort, UcpEventType

logger = logging.getLogger(__name__)


class UcpSyncWorkerService:
    def __init__(
        self,
        listener_port: UcpEventListenerPort,
        tenant_port: TenantPort,
        api_token_port: ApiTokenPort,
        sync_outbox_port: OutboxPort,
    ):
        self.listener_port = listener_port
        self.tenant_port = tenant_port
        self.api_token_port = api_token_port
        self.sync_outbox_port = sync_outbox_port

        # Event handler mapping to avoid if/else chains
        self._handlers: dict[str, Callable[[dict[str, Any]], Awaitable[None]]] = {
            UcpEventType.tenant_provisioned.value: self._handle_tenant_provisioned,
            UcpEventType.api_key_created.value: self._handle_api_key_created,
        }

    async def _handle_tenant_provisioned(self, payload: dict[str, Any]) -> None:
        tenant_id = str(payload["id"])
        name = payload["name"]

        logger.info(f"Syncing tenant {tenant_id} from UCP into EDI Global")

        # 1. Update the EDI Global database
        # This implementation details are hidden behind the port.
        await self.tenant_port.upsert_tenant(tenant_id, name)

        # 2. Drop a message into the local EDI outbox (edi.tenant.sync.fifo)
        # This delegates the shard replication to the existing provision worker.
        logger.info(f"Dispatching internal provisioning sync for tenant {tenant_id}")
        await self.sync_outbox_port.publish_event(
            event_type="tenant.sync",
            payload={"tenant_id": tenant_id},
            idempotency_key=f"sync_tenant_{tenant_id}",
            tenant_id=tenant_id
        )

    async def _handle_api_key_created(self, payload: dict[str, Any]) -> None:
        client_id = payload["id"]
        tenant_id = str(payload["tenantId"])
        name = payload["name"]
        key_hash = payload["keyHash"]

        logger.info(f"Syncing API Key {client_id} from UCP into EDI Global")

        # API Keys only reside in the global database for authentication by the edi-api.
        # They are not replicated to shards.
        await self.api_token_port.create_api_token(
            tenant_id=tenant_id,
            name=name,
            client_id=client_id,
            key_hash=key_hash
        )

    async def process_messages(self) -> None:
        """
        Polls the UCP event listener port and processes incoming Identity events.
        """
        async with self.listener_port.process_next_event() as event:
            if not event:
                return

            try:
                handler = self._handlers.get(event.eventType.value)
                if handler:
                    await handler(event.payload)
                else:
                    logger.debug(f"Ignored unhandled UCP event type: {event.eventType.value}")
            except Exception as e:
                logger.error(
                    f"Failed to process UCP event {event.eventType.value} "
                    f"(idempotency_key={event.idempotencyKey}): {e}"
                )
                raise
