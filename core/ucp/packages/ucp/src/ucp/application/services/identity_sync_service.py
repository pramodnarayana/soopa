import asyncio

import structlog

from ...ports.identity_provider import IdentityProviderPort
from ...ports.ucp_event_listener import UcpEventListenerPort

logger = structlog.get_logger(__name__)


class IdentitySyncService:
    """
    Pure business logic for synchronizing UCP domains (Tenants, Users)
    to an external Identity Provider (e.g. Zitadel).
    """

    def __init__(
        self,
        event_listener: UcpEventListenerPort,
        identity_provider: IdentityProviderPort,
    ):
        self.event_listener = event_listener
        self.identity_provider = identity_provider
        self.is_running = False
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info("identity_sync_service_started")

    async def stop(self) -> None:
        self.is_running = False
        if self._task:
            self._task.cancel()
            import contextlib

            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.info("identity_sync_service_stopped")

    async def _run_loop(self) -> None:
        try:
            # If the listener supports context management (e.g. SQS Connection pooling)
            if hasattr(self.event_listener, "__aenter__"):
                async with self.event_listener:  # type: ignore
                    await self._poll_continuous()
            else:
                await self._poll_continuous()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("identity_sync_service_run_loop_fatal_error")

    async def _poll_continuous(self) -> None:
        while self.is_running:
            try:
                # The listener manages the message lifecycle/ACK via context manager
                async with self.event_listener.process_next_event() as event:
                    if not event:
                        await asyncio.sleep(0.1)
                        continue

                    bound_logger = logger.bind(
                        tenant_id=event.tenant_id, event_type=event.event_type
                    )

                    if event.event_type == "tenant.provisioned":
                        bound_logger.info("syncing_tenant_to_identity_provider")
                        await self.identity_provider.sync_tenant(event.tenant_id)
                        bound_logger.debug("identity_sync_successful")
                    else:
                        bound_logger.debug("identity_sync_event_ignored")

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("identity_sync_service_poll_error")
                await asyncio.sleep(5)
