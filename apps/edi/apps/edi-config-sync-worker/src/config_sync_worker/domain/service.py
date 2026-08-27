from collections.abc import Awaitable, Callable
from typing import Any

from edi.domain.events import (
    EdiEventType,
    ProvisioningEvent,
    ProvisioningEventType,
    WebhookEventType,
)
from identity.domain.identity_context import PLATFORM_TENANT_ID

from config_sync_worker.domain.errors import PermanentProvisioningError, TransientProvisioningError
from config_sync_worker.ports.outbound.replication_port import ReplicationPort
from config_sync_worker.ports.outbound.tenant_port import TenantPort


class ProvisioningWorkerService:
    def __init__(
        self,
        tenant_port: TenantPort,
        replication_port: ReplicationPort,
    ):
        self.tenant_port = tenant_port
        self.replication_port = replication_port

        self._handlers: dict[ProvisioningEventType, Callable[[str, str], Awaitable[None]]] = {
            # AS2 Partner
            EdiEventType.edi_as2_partner_created: self.replication_port.replicate_as2_partner,
            EdiEventType.edi_as2_partner_updated: self.replication_port.replicate_as2_partner,
            EdiEventType.edi_as2_partner_deleted: self.replication_port.delete_as2_partner,
            # AS2 Partnership
            EdiEventType.edi_as2_partnership_created: self.replication_port.replicate_as2_partnership,
            EdiEventType.edi_as2_partnership_updated: self.replication_port.replicate_as2_partnership,
            EdiEventType.edi_as2_partnership_deleted: self.replication_port.delete_as2_partnership,
            # SFTP Partner
            EdiEventType.edi_sftp_partner_created: self.replication_port.replicate_sftp_partner,
            EdiEventType.edi_sftp_partner_updated: self.replication_port.replicate_sftp_partner,
            EdiEventType.edi_sftp_partner_deleted: self.replication_port.delete_sftp_partner,
            # Webhook
            WebhookEventType.webhook_created: self.replication_port.replicate_webhook,
            WebhookEventType.webhook_updated: self.replication_port.replicate_webhook,
            WebhookEventType.webhook_deleted: self.replication_port.delete_webhook,
            # Inbound Route
            EdiEventType.edi_inbound_route_created: self.replication_port.replicate_inbound_route,
            EdiEventType.edi_inbound_route_updated: self.replication_port.replicate_inbound_route,
            EdiEventType.edi_inbound_route_deleted: self.replication_port.delete_inbound_route,
            # Outbound Route
            EdiEventType.edi_outbound_route_created: self.replication_port.replicate_outbound_route,
            EdiEventType.edi_outbound_route_updated: self.replication_port.replicate_outbound_route,
            EdiEventType.edi_outbound_route_deleted: self.replication_port.delete_outbound_route,
            # Outbound EDI Header
            EdiEventType.edi_header_created: self.replication_port.replicate_outbound_edi_header,
            EdiEventType.edi_header_updated: self.replication_port.replicate_outbound_edi_header,
            EdiEventType.edi_header_deleted: self.replication_port.delete_outbound_edi_header,
        }

    async def _broadcast_or_replicate(self, tenant_id: str, replicate_fn: Any, *args: Any) -> None:
        if tenant_id == PLATFORM_TENANT_ID:
            all_tenants = await self.tenant_port.get_all_tenant_ids()
            transient_errors = []
            for t_id in all_tenants:
                try:
                    await replicate_fn(t_id, *args)
                except PermanentProvisioningError:
                    # Permanent errors are not retried or re-raised to block other tenants
                    pass

                except Exception as e:  # noqa: BLE001
                    transient_errors.append(e)
            if transient_errors:
                raise TransientProvisioningError(
                    f"Broadcast failed for some tenants: {transient_errors}"
                )
        else:
            await replicate_fn(tenant_id, *args)

    async def process_event(self, parsed_event: ProvisioningEvent) -> None:
        """Processes a strongly-typed domain event."""
        try:
            handler = self._handlers.get(parsed_event.event_type)
            if not handler:
                raise PermanentProvisioningError(f"Unhandled event type: {parsed_event.event_type}")

            await self._broadcast_or_replicate(
                parsed_event.tenant_id, handler, parsed_event.resource_id
            )
        except (PermanentProvisioningError, TransientProvisioningError):
            raise
        except Exception as e:
            raise TransientProvisioningError(f"Failed to process event: {e}") from e
