import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from domain.events import (
    EdiEventType,
    LegacyUcpEventType,
    ProvisioningEvent,
    ProvisioningEventType,
)
from identity.domain.identity_context import PLATFORM_TENANT_ID
from platform_schemas.webhook_events import WebhookEventType
from pydantic import TypeAdapter, ValidationError

from worker.core.errors import PermanentProvisioningError, TransientProvisioningError
from worker.ports.outbox import OutboxPort
from worker.ports.replication import ReplicationPort
from worker.ports.tenant import TenantPort

logger = logging.getLogger(__name__)


async def handle_provision_all_tenants(
    service: "ProvisioningWorkerService", event: ProvisioningEvent, event_id: str
) -> None:
    logger.info(f"Processing provision event {event_id} for all tenants. Broadcasting...")
    try:
        all_tenant_ids = await service.tenant_port.get_all_tenant_ids()
        _semaphore = asyncio.Semaphore(10)

        async def _replicate(t_id: str) -> None:
            async with _semaphore:
                await service.replication_port.replicate_tenant_configuration(t_id)

        results = await asyncio.gather(
            *[_replicate(t_id) for t_id in all_tenant_ids], return_exceptions=True
        )

        errors = []
        for t_id, result in zip(all_tenant_ids, results, strict=False):
            if isinstance(result, Exception):
                logger.exception(
                    f"Failed to broadcast global event {event_id} to tenant {t_id}: {result}",
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


class ProvisioningWorkerService:
    def __init__(
        self, tenant_port: TenantPort, outbox_port: OutboxPort, replication_port: ReplicationPort
    ):
        self.tenant_port = tenant_port
        self.outbox_port = outbox_port
        self.replication_port = replication_port

        # Instantiate the type adapter for our union once
        self._event_adapter: TypeAdapter[ProvisioningEvent] = TypeAdapter(ProvisioningEvent)

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
            logger.info(
                f"Master Tenant detected. Broadcasting global platform event {replicate_fn.__name__} to all tenant databases"
            )
            all_tenants = await self.tenant_port.get_all_tenant_ids()
            transient_errors = []
            for t_id in all_tenants:
                try:
                    await replicate_fn(t_id, *args)
                except PermanentProvisioningError as e:
                    # Log permanent errors but don't retry them
                    logger.error(f"Permanent error for tenant {t_id}: {e}")
                except Exception as e:
                    transient_errors.append(e)
            if transient_errors:
                raise TransientProvisioningError(
                    f"Broadcast failed for some tenants: {transient_errors}"
                )
        else:
            await replicate_fn(tenant_id, *args)

    async def process_next_event(self) -> bool:
        """Process a single event from the outbox. Returns True if an event was processed."""
        async with self.outbox_port.process_next_event() as event:
            if not event:
                return False

            body = event.body

            try:
                # The SQS event built by the sweeper is a single flat JSON object containing both metadata and payload fields.
                parsed_event = self._event_adapter.validate_python(body)
            except ValidationError as e:
                # If we don't know how to handle it, we permanently fail it so it goes to DLQ
                logger.error(f"Validation error for event type '{event.event_type}': {e}")
                raise PermanentProvisioningError(
                    f"Invalid provision event payload for {event.event_type}: {e}"
                ) from e

            try:
                if parsed_event.event_type == LegacyUcpEventType.PROVISION_ALL_TENANTS:
                    await handle_provision_all_tenants(self, parsed_event, str(event.id))
                elif parsed_event.event_type == LegacyUcpEventType.PROVISION_TENANT:
                    logger.info(f"Provisioning tenant configuration for {parsed_event.tenant_id}")
                    await self.replication_port.replicate_tenant_configuration(
                        parsed_event.tenant_id
                    )
                else:
                    if parsed_event.resource_id is None:
                        raise PermanentProvisioningError(
                            f"Event {parsed_event.event_type} missing required resource_id"
                        )

                    handler = self._handlers.get(parsed_event.event_type)
                    if not handler:
                        raise PermanentProvisioningError(
                            f"Unhandled event type: {parsed_event.event_type}"
                        )

                    logger.info(
                        f"Processing {parsed_event.event_type} for resource {parsed_event.resource_id} in tenant {parsed_event.tenant_id}"
                    )
                    await self._broadcast_or_replicate(
                        parsed_event.tenant_id, handler, parsed_event.resource_id
                    )
            except PermanentProvisioningError:
                raise
            except TransientProvisioningError:
                raise
            except Exception as e:
                logger.error(f"Failed to process event {event.id}: {e}")
                raise TransientProvisioningError(f"Failed to process event {event.id}: {e}") from e

        return True
