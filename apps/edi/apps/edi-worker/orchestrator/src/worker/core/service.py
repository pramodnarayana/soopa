import logging

from worker.core.errors import PermanentProvisioningError, TransientProvisioningError
from worker.ports.outbox import OutboxPort
from worker.ports.replication import ReplicationPort
from worker.ports.tenant import TenantPort

logger = logging.getLogger(__name__)


class ProvisioningWorkerService:
    def __init__(
        self, tenant_port: TenantPort, outbox_port: OutboxPort, replication_port: ReplicationPort
    ):
        self.tenant_port = tenant_port
        self.outbox_port = outbox_port
        self.replication_port = replication_port

    async def process_next_event(self) -> bool:
        """Process a single event from the outbox. Returns True if an event was processed."""
        async with self.outbox_port.process_next_event() as event:
            if not event:
                return False

            from pydantic import TypeAdapter, ValidationError

            from worker.core.schemas import (
                ProvisionAllTenantsEvent,
                ProvisionEventPayload,
                ProvisionTenantEvent,
            )

            payload = event.payload

            try:
                parsed_payload = TypeAdapter(ProvisionEventPayload).validate_python(payload)
            except ValidationError as e:
                raise PermanentProvisioningError(f"Invalid provision event payload: {e}") from e

            if isinstance(parsed_payload, ProvisionAllTenantsEvent):
                logger.info(
                    f"Processing provision event {event.id} for all tenants. Broadcasting..."
                )
                try:
                    all_tenant_ids = await self.tenant_port.get_all_tenant_ids()

                    # Bounded concurrency: replicate to all tenants concurrently but cap
                    # the number of simultaneous DB connections to avoid overwhelming the
                    # connection pool. Combined with deterministic ORDER BY id in the
                    # replication adapter, this eliminates deadlocks while remaining scalable.
                    import asyncio

                    _semaphore = asyncio.Semaphore(10)

                    async def _replicate(t_id: str) -> None:
                        async with _semaphore:
                            await self.replication_port.replicate_tenant_configuration(t_id)

                    results = await asyncio.gather(
                        *[_replicate(t_id) for t_id in all_tenant_ids], return_exceptions=True
                    )

                    errors = []
                    for t_id, result in zip(all_tenant_ids, results, strict=False):
                        if isinstance(result, Exception):
                            logger.exception(
                                f"Failed to broadcast global event {event.id} to tenant {t_id}: {result}",
                                exc_info=result,
                            )
                            if not isinstance(result, PermanentProvisioningError):
                                errors.append(result)

                    if errors:
                        raise TransientProvisioningError(
                            f"Global broadcasting failed for some tenants: {errors}"
                        )

                except Exception as e:
                    if isinstance(e, TransientProvisioningError):
                        raise
                    raise TransientProvisioningError(f"Global broadcasting failed: {e}") from e
            elif isinstance(parsed_payload, ProvisionTenantEvent):
                tenant_id = parsed_payload.tenant_id
                logger.info(f"Processing provision event {event.id} for tenant_id={tenant_id}")
                await self.replication_port.replicate_tenant_configuration(tenant_id)

        return True
