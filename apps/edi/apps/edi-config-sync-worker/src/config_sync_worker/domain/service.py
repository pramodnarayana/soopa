from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from edi.domain.events import (
    EdiEventType,
    ProvisioningEvent,
    ProvisioningEventType,
    WebhookEventType,
)
from identity.domain.identity_context import PLATFORM_TENANT_ID
from pydantic import TypeAdapter, ValidationError

from config_sync_worker.domain.errors import PermanentProvisioningError, TransientProvisioningError
from config_sync_worker.ports.outbound.event_translator_port import EventTranslatorPort
from config_sync_worker.ports.outbound.outbox_port import OutboxPort
from config_sync_worker.ports.outbound.replication_port import ReplicationPort
from config_sync_worker.ports.outbound.tenant_port import TenantPort

logger = structlog.get_logger(__name__)


class ProvisioningWorkerService:
    def __init__(
        self,
        tenant_port: TenantPort,
        outbox_port: OutboxPort,
        replication_port: ReplicationPort,
        translator_port: EventTranslatorPort,
    ):
        self.tenant_port = tenant_port
        self.outbox_port = outbox_port
        self.replication_port = replication_port
        self.translator_port = translator_port

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
                "master_tenant_detected_broadcasting",
                replicate_fn=replicate_fn.__name__,
            )
            all_tenants = await self.tenant_port.get_all_tenant_ids()
            transient_errors = []
            for t_id in all_tenants:
                try:
                    await replicate_fn(t_id, *args)
                except PermanentProvisioningError:
                    # Log permanent errors but don't retry them
                    logger.exception("permanent_provisioning_error_ignored", tenant_id=t_id)

                except Exception as e:  # noqa: BLE001
                    transient_errors.append(e)
            if transient_errors:
                raise TransientProvisioningError(
                    f"Broadcast failed for some tenants: {transient_errors}"
                )
        else:
            await replicate_fn(tenant_id, *args)

    def _parse_event(self, envelope: Any) -> ProvisioningEvent | None:
        try:
            if envelope.source == "soopa.ucp":
                translated_payload = self.translator_port.translate_external_event(
                    envelope.event_type, envelope.payload
                )
                if not translated_payload:
                    logger.warning(
                        "unregistered_external_event_type",
                        external_event_type=envelope.event_type,
                        event_id=envelope.id,
                    )
                    return None
                return self._event_adapter.validate_python(translated_payload)
            elif envelope.source == "soopa.edi":
                event_dict = {
                    "tenant_id": envelope.tenant_id,
                    "event_type": envelope.event_type,
                    "resource_id": envelope.payload.get("resource_id")
                    or envelope.payload.get("id"),
                }
                return self._event_adapter.validate_python(event_dict)
            else:
                logger.warning("unknown_event_source", source=envelope.source, event_id=envelope.id)
                return None
        except ValidationError as e:
            # If we don't know how to handle it, we permanently fail it so it goes to DLQ
            logger.exception("provisioning_event_validation_error", event_type=envelope.event_type)
            raise PermanentProvisioningError(
                f"Invalid provision event payload for {envelope.event_type}: {e}"
            ) from e

    async def process_next_event(self) -> bool:
        """Process a single event from the outbox. Returns True if an event was processed."""
        async with self.outbox_port.process_next_event() as event:
            if not event:
                return False

            envelope = getattr(event, "envelope", None)
            if not envelope:
                logger.error("invalid_event_format_no_envelope", event_id=event.id)
                raise PermanentProvisioningError("Event is missing envelope attribute")

            parsed_event = self._parse_event(envelope)
            if not parsed_event:
                return True

            try:
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
                    "dispatching_provision_event",
                    event_type=parsed_event.event_type,
                    resource_id=parsed_event.resource_id,
                    tenant_id=parsed_event.tenant_id,
                )
                await self._broadcast_or_replicate(
                    parsed_event.tenant_id, handler, parsed_event.resource_id
                )
            except (PermanentProvisioningError, TransientProvisioningError):
                raise
            except Exception as e:
                logger.exception("provisioning_event_processing_failed", event_id=envelope.id)
                raise TransientProvisioningError(
                    f"Failed to process event {envelope.id}: {e}"
                ) from e

        return True
