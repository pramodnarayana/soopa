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

            payload = event.payload
            tenant_id = payload.get("tenant_id")

            if tenant_id is None:
                raise PermanentProvisioningError("Missing tenant_id in provision event payload")

            if tenant_id == 0:
                logger.info(
                    f"Processing GLOBAL provision event {event.id} (tenant_id=0). Broadcasting to all tenants."
                )
                try:
                    all_tenant_ids = await self.tenant_port.get_all_tenant_ids()
                    for t_id in all_tenant_ids:
                        try:
                            await self.replication_port.replicate_tenant_configuration(t_id)
                        except Exception as e:
                            logger.exception(
                                f"Failed to broadcast global event {event.id} to tenant {t_id}: {e}"
                            )
                except Exception as e:
                    raise TransientProvisioningError(f"Global broadcasting failed: {e}") from e
            else:
                logger.info(f"Processing provision event {event.id} for tenant_id={tenant_id}")
                await self.replication_port.replicate_tenant_configuration(tenant_id)

        return True
