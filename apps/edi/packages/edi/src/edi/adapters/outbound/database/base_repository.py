from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol, cast

from config_sync.domain.checksum import compute_payload_checksum
from config_sync.domain.enums import ConfigChangeAction, ConfigSyncChannel
from identity.domain.identity_context import PLATFORM_TENANT_ID
from outbox.domain.constants import OutboxStatus
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.events import DomainEvent
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import select
from sqlalchemy.orm import Mapped

from database.config_changelog import record_config_changelog_entry
from database.outbox_serializer import serialize_domain_event
from database.repository import BaseSqlAlchemyRepository as PlatformBaseSqlAlchemyRepository
from database.types import GlobalSession as GlobalSession
from database.types import TenantSession as TenantSession
from edi.adapters.outbound.database.models.control_plane import ControlPlaneOutbox
from edi.adapters.outbound.database.replication_registry import REPLICATION_GRAPH
from edi.domain.enums import EDI_CONFIG_APP_ID, EdiEventType
from edi.domain.routing.enums import WebhookEventType

_EDI_CONFIG_SYNC_EVENTS: dict[str, tuple[str, ConfigChangeAction]] = {
    EdiEventType.edi_as2_partner_created.value: ("as2_partner", ConfigChangeAction.UPSERT),
    EdiEventType.edi_as2_partner_updated.value: ("as2_partner", ConfigChangeAction.UPSERT),
    EdiEventType.edi_as2_partner_deleted.value: ("as2_partner", ConfigChangeAction.DELETE),
    EdiEventType.edi_as2_partnership_created.value: ("as2_partnership", ConfigChangeAction.UPSERT),
    EdiEventType.edi_as2_partnership_updated.value: ("as2_partnership", ConfigChangeAction.UPSERT),
    EdiEventType.edi_as2_partnership_deleted.value: ("as2_partnership", ConfigChangeAction.DELETE),
    EdiEventType.edi_sftp_partner_created.value: ("sftp_partner", ConfigChangeAction.UPSERT),
    EdiEventType.edi_sftp_partner_updated.value: ("sftp_partner", ConfigChangeAction.UPSERT),
    EdiEventType.edi_sftp_partner_deleted.value: ("sftp_partner", ConfigChangeAction.DELETE),
    WebhookEventType.webhook_created.value: ("webhook", ConfigChangeAction.UPSERT),
    WebhookEventType.webhook_updated.value: ("webhook", ConfigChangeAction.UPSERT),
    WebhookEventType.webhook_deleted.value: ("webhook", ConfigChangeAction.DELETE),
    EdiEventType.edi_inbound_route_created.value: ("inbound_route", ConfigChangeAction.UPSERT),
    EdiEventType.edi_inbound_route_updated.value: ("inbound_route", ConfigChangeAction.UPSERT),
    EdiEventType.edi_inbound_route_deleted.value: ("inbound_route", ConfigChangeAction.DELETE),
    EdiEventType.edi_outbound_route_created.value: ("outbound_route", ConfigChangeAction.UPSERT),
    EdiEventType.edi_outbound_route_updated.value: ("outbound_route", ConfigChangeAction.UPSERT),
    EdiEventType.edi_outbound_route_deleted.value: ("outbound_route", ConfigChangeAction.DELETE),
    EdiEventType.edi_header_created.value: ("outbound_edi_header", ConfigChangeAction.UPSERT),
    EdiEventType.edi_header_updated.value: ("outbound_edi_header", ConfigChangeAction.UPSERT),
    EdiEventType.edi_header_deleted.value: ("outbound_edi_header", ConfigChangeAction.DELETE),
}

_RESOURCE_ID_KEYS: tuple[str, ...] = (
    "partner_id",
    "partnership_id",
    "webhook_id",
    "route_id",
    "header_id",
    "resource_id",
    "id",
)


class _IdentifiableModel(Protocol):
    id: Mapped[str]


def _normalize_changelog_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _normalize_changelog_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_changelog_value(item) for item in value]
    return str(value)


def _extract_resource_id(payload_dict: Mapping[str, object]) -> str:
    for key in _RESOURCE_ID_KEYS:
        val = payload_dict.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


class DomainEventCarrier(Protocol):
    @property
    def domain_events(self) -> Sequence[DomainEvent]: ...

    def clear_domain_events(self) -> None: ...


class GlobalSqlAlchemyRepository(PlatformBaseSqlAlchemyRepository):
    """
    Base class for Control Plane repositories.
    Strictly enforces that the injected session is a GlobalSession.
    """

    session: GlobalSession

    def __init__(self, session: GlobalSession) -> None:
        info = session.info
        if isinstance(info, dict) and info.get("session_type") != "global":
            raise ValueError(
                f"Expected a GlobalSession but received a {info.get('session_type')} session. "
                "Check the UnitOfWork or dependencies injection."
            )
        self.session = session

    async def _drain_events(self, aggregate: DomainEventCarrier) -> None:
        for event in aggregate.domain_events:
            event_name = event.event_name
            payload_dict = serialize_domain_event(event)
            tenant_id = event.get_routing_tenant_id() or PLATFORM_TENANT_ID

            if event.idempotency_key:
                res = await self.session.execute(
                    select(ControlPlaneOutbox).where(
                        ControlPlaneOutbox.idempotency_key == event.idempotency_key,
                        ControlPlaneOutbox.status == OutboxStatus.RESERVED,
                    )
                )
                reservation = res.scalar_one_or_none()
                if reservation is not None:
                    reservation.event_type = event_name
                    current_payload = reservation.payload or {}
                    if isinstance(current_payload, dict):
                        reservation.payload = {**current_payload, **payload_dict}
                    else:
                        reservation.payload = payload_dict
                    reservation.status = OutboxStatus.PENDING
                    await self._record_config_sync_changelog(
                        event_name=event_name,
                        tenant_id=tenant_id,
                        payload_dict=payload_dict,
                    )
                    continue

            outbox_id = generate_id(ControlPlaneOutbox.ID_PREFIX)
            outbox_event = ControlPlaneOutbox(
                id=outbox_id,
                idempotency_key=event.idempotency_key,
                tenant_id=tenant_id,
                event_type=event_name,
                payload=payload_dict,
                status=OutboxStatus.PENDING,
            )
            self.session.add(outbox_event)

            await self._record_config_sync_changelog(
                event_name=event_name,
                tenant_id=tenant_id,
                payload_dict=payload_dict,
            )

        aggregate.clear_domain_events()

    async def _record_config_sync_changelog(
        self,
        *,
        event_name: str,
        tenant_id: str,
        payload_dict: Mapping[str, object],
    ) -> None:
        mapping = _EDI_CONFIG_SYNC_EVENTS.get(event_name)
        if mapping is None:
            return
        entity_type, action = mapping
        entity_id = _extract_resource_id(payload_dict)
        if not entity_id:
            return

        changelog_payload: JsonDict = {
            str(k): _normalize_changelog_value(v) for k, v in payload_dict.items()
        }
        if action == ConfigChangeAction.UPSERT and entity_type in REPLICATION_GRAPH:
            await self.session.flush()
            spec = REPLICATION_GRAPH[entity_type]
            cp_model = cast(type[_IdentifiableModel], spec.control_plane_model)
            row = (
                await self.session.execute(select(cp_model).where(cp_model.id == entity_id))
            ).scalar_one_or_none()
            if row is not None:
                mapped = dict(spec.map_entity(row))
                changelog_payload = {
                    str(k): _normalize_changelog_value(v) for k, v in mapped.items()
                }

        await record_config_changelog_entry(
            self.session,
            event_id=generate_id(SystemIdPrefix.GENERIC),
            app_id=EDI_CONFIG_APP_ID,
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action.value,
            checksum=compute_payload_checksum(changelog_payload),
            payload=dict(changelog_payload),
            notify_channel=ConfigSyncChannel.CONFIG_CHANGELOG_NOTIFY.value,
        )


class TenantSqlAlchemyRepository(PlatformBaseSqlAlchemyRepository):
    """
    Base class for Data Plane / Shard repositories.
    Strictly enforces that the injected session is a TenantSession.
    """

    session: TenantSession

    def __init__(self, session: TenantSession) -> None:
        info = session.info
        if isinstance(info, dict) and info.get("session_type") != "tenant":
            raise ValueError(
                f"Expected a TenantSession but received a {info.get('session_type')} session. "
                "Check the UnitOfWork or dependencies injection."
            )
        self.session = session
