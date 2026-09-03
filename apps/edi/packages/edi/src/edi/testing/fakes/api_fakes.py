from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TypeVar

from database.exceptions import DuplicateEntityError
from database.outbox_serializer import serialize_domain_event
from identity.domain.identity_context import PLATFORM_TENANT_ID
from seedwork.constants import SystemIdPrefix
from seedwork.domain.types import JsonValue
from seedwork.models import AggregateRoot
from seedwork.utils import generate_id

from edi.application.dtos.commands import (
    UNSET,
    CreateAS2PartnershipCmd,
    CreateAS2TradingPartnerCmd,
    CreateInboundRouteCmd,
    CreateOutboundRouteCmd,
    CreateSFTPPartnerCmd,
    UpdateAS2PartnershipCmd,
    UpdateAS2TradingPartnerCmd,
    UpdateInboundRouteCmd,
    UpdateOutboundRouteCmd,
    UpdateSFTPPartnerCmd,
)
from edi.domain.exceptions import IdempotencyConflictError, PartnerAlreadyExistsError
from edi.domain.models.as2 import AS2PartnerDomainModel, AS2PartnershipDomainModel
from edi.domain.models.headers import OutboundEdiHeaderDomainModel
from edi.domain.models.inbound_routes import InboundRouteDomainModel
from edi.domain.models.outbound_routes import OutboundRouteDomainModel
from edi.domain.models.outbox_event import OutboxEvent
from edi.domain.models.sftp import SFTPPartnerDomainModel
from edi.domain.models.webhooks import WebhookDomainModel
from edi.ports.outbound.repository import (
    TenantRepositoryPort,
)

T = TypeVar("T")


class FakeOutboxBase:
    """Shared outbox store across repositories within a UOW to accumulate events."""

    def __init__(self):
        self.outbox_events: list[OutboxEvent] = []

    def append(self, event: OutboxEvent):
        self.outbox_events.append(event)


class FakeInboundRouteRepository:
    def __init__(self, outbox: FakeOutboxBase) -> None:
        self.inbound_routes: dict[str, InboundRouteDomainModel] = {}
        self.outbox = outbox

    async def get_inbound_routes(self, tenant_id: str) -> list[object]:
        return [
            r for r in self.inbound_routes.values() if getattr(r, "tenant_id", None) == tenant_id
        ]

    async def get_inbound_route(self, tenant_id: str, route_id: str) -> object | None:
        route = self.inbound_routes.get(route_id)
        return route if route and getattr(route, "tenant_id", None) == tenant_id else None

    async def get_inbound_route_by_id(self, tenant_id: str, route_id: str) -> object | None:
        return await self.get_inbound_route(tenant_id, route_id)

    async def create_inbound_route(self, tenant_id: str, cmd: CreateInboundRouteCmd) -> str:
        r_id = generate_id(SystemIdPrefix.GENERIC)
        now = datetime.now(UTC).replace(tzinfo=None)
        from edi.domain.models.base import ProcessingMode

        pm = (
            ProcessingMode(cmd.processing_mode) if cmd.processing_mode else ProcessingMode.TRANSFORM
        )
        self.inbound_routes[r_id] = InboundRouteDomainModel(
            id=r_id,
            tenant_id=tenant_id,
            name=cmd.name,
            active=True,
            isa_sender_id=cmd.isa_sender_id,
            isa_receiver_id=cmd.isa_receiver_id,
            gs_sender_id=cmd.gs_sender_id,
            gs_receiver_id=cmd.gs_receiver_id,
            transaction_type=cmd.transaction_type,
            trading_partner_id=cmd.trading_partner_id,
            processing_mode=pm,
            created_at=now,
            updated_at=now,
        )
        return r_id

    async def update_inbound_route(
        self, tenant_id: str, route_id: str, cmd: UpdateInboundRouteCmd
    ) -> bool:
        route = self.inbound_routes.get(route_id)
        return bool(route and route.tenant_id == tenant_id)

    async def delete_inbound_route(self, tenant_id: str, route_id: str) -> bool:
        route = self.inbound_routes.get(route_id)
        if route and route.tenant_id == tenant_id:
            del self.inbound_routes[route_id]
            return True
        return False

    async def list_inbound_routes(self, tenant_id: str) -> list[object]:
        return [
            r for r in self.inbound_routes.values() if getattr(r, "tenant_id", None) == tenant_id
        ]

    async def get_tenant_by_isa(self, isa_sender_id: str, isa_receiver_id: str) -> str | None:
        for r in self.inbound_routes.values():
            if r.isa_sender_id == isa_sender_id and r.isa_receiver_id == isa_receiver_id:
                return r.tenant_id
        return None

    async def save(self, aggregate: AggregateRoot) -> None:
        if isinstance(aggregate, InboundRouteDomainModel):
            self.inbound_routes[aggregate.id] = aggregate
        self._flush_events(aggregate)

    async def delete(self, aggregate: AggregateRoot) -> None:
        if isinstance(aggregate, InboundRouteDomainModel):
            self.inbound_routes.pop(aggregate.id, None)
        self._flush_events(aggregate)

    def _flush_events(self, aggregate: AggregateRoot):
        for event in aggregate.domain_events:
            self.outbox.append(
                OutboxEvent(
                    id=generate_id(SystemIdPrefix.GENERIC),
                    tenant_id=str(
                        getattr(event, "get_routing_tenant_id", lambda: None)()
                        or getattr(aggregate, "tenant_id", PLATFORM_TENANT_ID)
                    ),
                    event_type=str(getattr(event, "event_name", type(event).__name__)),
                    payload=serialize_domain_event(event),
                    idempotency_key=getattr(event, "idempotency_key", None),
                )
            )
        aggregate.clear_domain_events()


class FakeOutboundRouteRepository:
    def __init__(self, outbox: FakeOutboxBase) -> None:
        self.outbound_routes: dict[str, OutboundRouteDomainModel] = {}
        self.outbox = outbox

    async def get_outbound_routes(self, tenant_id: str) -> list[object]:
        return [
            r for r in self.outbound_routes.values() if getattr(r, "tenant_id", None) == tenant_id
        ]

    async def get_outbound_route(self, tenant_id: str, route_id: str) -> object | None:
        route = self.outbound_routes.get(route_id)
        return route if route and route.tenant_id == tenant_id else None

    async def create_outbound_route(self, tenant_id: str, cmd: CreateOutboundRouteCmd) -> str:
        r_id = generate_id(SystemIdPrefix.GENERIC)
        now = datetime.now(UTC).replace(tzinfo=None)
        self.outbound_routes[r_id] = OutboundRouteDomainModel(
            id=r_id,
            tenant_id=tenant_id,
            name=cmd.name,
            active=True,
            trading_partner_id=cmd.trading_partner_id,
            protocol=cmd.protocol,
            as2_partner_id=cmd.as2_partner_id,
            sftp_partner_id=cmd.sftp_partner_id,
            created_at=now,
            updated_at=now,
        )
        return r_id

    async def update_outbound_route(
        self, tenant_id: str, route_id: str, cmd: UpdateOutboundRouteCmd
    ) -> bool:
        route = self.outbound_routes.get(route_id)
        return bool(route and route.tenant_id == tenant_id)

    async def delete_outbound_route(self, tenant_id: str, route_id: str) -> bool:
        route = self.outbound_routes.get(route_id)
        if route and route.tenant_id == tenant_id:
            del self.outbound_routes[route_id]
            return True
        return False

    async def list_outbound_routes(self, tenant_id: str) -> list[object]:
        return [
            r for r in self.outbound_routes.values() if getattr(r, "tenant_id", None) == tenant_id
        ]

    async def save(self, aggregate: AggregateRoot) -> None:
        if isinstance(aggregate, OutboundRouteDomainModel):
            self.outbound_routes[aggregate.id] = aggregate
        self._flush_events(aggregate)

    async def delete(self, aggregate: AggregateRoot) -> None:
        if isinstance(aggregate, OutboundRouteDomainModel):
            self.outbound_routes.pop(aggregate.id, None)
        self._flush_events(aggregate)

    def _flush_events(self, aggregate: AggregateRoot):
        for event in aggregate.domain_events:
            self.outbox.append(
                OutboxEvent(
                    id=generate_id(SystemIdPrefix.GENERIC),
                    tenant_id=str(
                        getattr(event, "get_routing_tenant_id", lambda: None)()
                        or getattr(aggregate, "tenant_id", PLATFORM_TENANT_ID)
                    ),
                    event_type=str(getattr(event, "event_name", type(event).__name__)),
                    payload=serialize_domain_event(event),
                    idempotency_key=getattr(event, "idempotency_key", None),
                )
            )
        aggregate.clear_domain_events()


class FakeAS2PartnerRepository:
    def __init__(self, outbox: FakeOutboxBase) -> None:
        self.partners: dict[str, AS2PartnerDomainModel] = {}
        self.outbox = outbox

    async def create_as2_identity(self, tenant_id: str, cmd: CreateAS2TradingPartnerCmd) -> str:
        for p in self.partners.values():
            if (
                isinstance(p, AS2PartnerDomainModel)
                and p.tenant_id == str(tenant_id)
                and p.as2_id == cmd.as2_id
            ):
                raise PartnerAlreadyExistsError(as2_id=cmd.as2_id, tenant_id=str(tenant_id))
        partner_id = generate_id(SystemIdPrefix.GENERIC)
        now = datetime.now(UTC).replace(tzinfo=None)
        aggregate = AS2PartnerDomainModel(
            id=partner_id,
            tenant_id=str(tenant_id),
            as2_id=cmd.as2_id,
            name=cmd.name,
            is_local=cmd.is_local,
            url=cmd.url,
            public_cert_pem=cmd.public_cert_pem,
            public_cert_vault_ref=cmd.public_cert_vault_ref,
            active=False,
            created_at=now,
            updated_at=now,
        )
        self.partners[partner_id] = aggregate
        return partner_id

    async def update_as2_identity(
        self, tenant_id: str, partner_id: str, cmd: UpdateAS2TradingPartnerCmd
    ) -> None:
        if partner_id in self.partners and self.partners[partner_id].tenant_id == tenant_id:
            p = self.partners[partner_id]
            p.name = getattr(cmd, "name", p.name)

    async def delete_as2_identity(self, tenant_id: str, partner_id: str) -> None:
        if partner_id in self.partners and self.partners[partner_id].tenant_id == tenant_id:
            del self.partners[partner_id]

    async def get_as2_partner(self, tenant_id: str, partner_id: str) -> object | None:
        p = self.partners.get(partner_id)
        return p if p and getattr(p, "tenant_id", None) == tenant_id else None

    async def update_partner_status(self, tenant_id: str, partner_id: str, status: str) -> None:
        if partner_id in self.partners and self.partners[partner_id].tenant_id == tenant_id:
            self.partners[partner_id].active = status == "ACTIVE"

    async def list_trading_partners(self) -> list[object]:
        return list(self.partners.values())

    async def list_as2_partners(self, tenant_id: str) -> Sequence[object]:
        return [p for p in self.partners.values() if getattr(p, "tenant_id", None) == tenant_id]

    async def get_as2_partners_by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, str]:
        return {
            id: self.partners[id].name
            for id in ids
            if id in self.partners and self.partners[id].tenant_id == str(tenant_id)
        }

    async def is_vault_ref_in_use(self, vault_ref: str) -> bool:
        for p in self.partners.values():
            if isinstance(p, AS2PartnerDomainModel) and (
                p.private_key_vault_ref == vault_ref or p.public_cert_vault_ref == vault_ref
            ):
                return True
        return False

    async def save(self, aggregate: AggregateRoot) -> None:
        if isinstance(aggregate, AS2PartnerDomainModel):
            for existing in self.partners.values():
                if (
                    isinstance(existing, AS2PartnerDomainModel)
                    and existing.id != aggregate.id
                    and existing.tenant_id == aggregate.tenant_id
                    and existing.as2_id == aggregate.as2_id
                ):
                    raise PartnerAlreadyExistsError(
                        as2_id=aggregate.as2_id, tenant_id=aggregate.tenant_id or PLATFORM_TENANT_ID
                    )
            self.partners[aggregate.id] = aggregate
        self._flush_events(aggregate)

    async def delete(self, aggregate: AggregateRoot) -> None:
        if isinstance(aggregate, AS2PartnerDomainModel):
            self.partners.pop(aggregate.id, None)
        self._flush_events(aggregate)

    def _flush_events(self, aggregate: AggregateRoot):
        for event in aggregate.domain_events:
            self.outbox.append(
                OutboxEvent(
                    id=generate_id(SystemIdPrefix.GENERIC),
                    tenant_id=str(
                        getattr(event, "get_routing_tenant_id", lambda: None)()
                        or getattr(aggregate, "tenant_id", PLATFORM_TENANT_ID)
                    ),
                    event_type=str(getattr(event, "event_name", type(event).__name__)),
                    payload=serialize_domain_event(event),
                    idempotency_key=getattr(event, "idempotency_key", None),
                )
            )
        aggregate.clear_domain_events()


class FakeSFTPPartnerRepository:
    def __init__(self, outbox: FakeOutboxBase) -> None:
        self.sftp_partners: dict[str, SFTPPartnerDomainModel] = {}
        self.outbox = outbox

    async def create_sftp_partner(self, tenant_id: str, cmd: CreateSFTPPartnerCmd) -> str:
        partner_id = generate_id(SystemIdPrefix.GENERIC)
        now = datetime.now(UTC).replace(tzinfo=None)
        aggregate = SFTPPartnerDomainModel(
            id=partner_id,
            tenant_id=str(tenant_id),
            name=cmd.name,
            host=cmd.host,
            port=cmd.port,
            username=cmd.username,
            inbound_remote_path=cmd.inbound_remote_path,
            outbound_remote_path=cmd.outbound_remote_path,
            credentials_vault_ref=cmd.credentials_vault_ref,
            active=False,
            created_at=now,
            updated_at=now,
        )
        self.sftp_partners[partner_id] = aggregate
        return partner_id

    async def update_sftp_partner(
        self, tenant_id: str, partner_id: str, cmd: UpdateSFTPPartnerCmd
    ) -> bool:
        if (
            partner_id in self.sftp_partners
            and self.sftp_partners[partner_id].tenant_id == tenant_id
        ):
            p = self.sftp_partners[partner_id]
            if not isinstance(cmd.active, type(UNSET)):
                p.active = bool(cmd.active)
            return True
        return False

    async def delete_sftp_partner(self, tenant_id: str, partner_id: str) -> None:
        if (
            partner_id in self.sftp_partners
            and self.sftp_partners[partner_id].tenant_id == tenant_id
        ):
            del self.sftp_partners[partner_id]

    async def get_sftp_partner(self, tenant_id: str, partner_id: str) -> object | None:
        p = self.sftp_partners.get(partner_id)
        return p if p and getattr(p, "tenant_id", None) == tenant_id else None

    async def list_sftp_partners(self, tenant_id: str) -> Sequence[object]:
        return [
            p for p in self.sftp_partners.values() if getattr(p, "tenant_id", None) == tenant_id
        ]

    async def get_sftp_partners_by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, str]:
        return {
            id: getattr(self.sftp_partners[id], "name", "unknown")
            for id in ids
            if id in self.sftp_partners
            and getattr(self.sftp_partners[id], "tenant_id", None) == str(tenant_id)
        }

    async def save(self, aggregate: AggregateRoot) -> None:
        if isinstance(aggregate, SFTPPartnerDomainModel):
            self.sftp_partners[aggregate.id] = aggregate
        self._flush_events(aggregate)

    async def delete(self, aggregate: AggregateRoot) -> None:
        if isinstance(aggregate, SFTPPartnerDomainModel):
            self.sftp_partners.pop(aggregate.id, None)
        self._flush_events(aggregate)

    def _flush_events(self, aggregate: AggregateRoot):
        for event in aggregate.domain_events:
            self.outbox.append(
                OutboxEvent(
                    id=generate_id(SystemIdPrefix.GENERIC),
                    tenant_id=str(
                        getattr(event, "get_routing_tenant_id", lambda: None)()
                        or getattr(aggregate, "tenant_id", PLATFORM_TENANT_ID)
                    ),
                    event_type=str(getattr(event, "event_name", type(event).__name__)),
                    payload=serialize_domain_event(event),
                    idempotency_key=getattr(event, "idempotency_key", None),
                )
            )
        aggregate.clear_domain_events()


class FakeAS2PartnershipRepository:
    def __init__(self, outbox: FakeOutboxBase, partners_repo: FakeAS2PartnerRepository) -> None:
        self.partnerships: dict[str, AS2PartnershipDomainModel] = {}
        self.outbox = outbox
        self.partners_repo = partners_repo

    async def create_as2_partnership(self, tenant_id: str, cmd: CreateAS2PartnershipCmd) -> str:
        p_id = generate_id(SystemIdPrefix.GENERIC)
        now = datetime.now(UTC).replace(tzinfo=None)
        self.partnerships[p_id] = AS2PartnershipDomainModel(
            id=p_id,
            tenant_id=tenant_id,
            name=cmd.name,
            local_partner_id=cmd.local_partner_id,
            remote_partner_id=cmd.remote_partner_id,
            mdn_type=cmd.mdn_type,
            mdn_url=cmd.mdn_url,
            encryption_algorithm=cmd.encryption_algorithm,
            signature_algorithm=cmd.signature_algorithm,
            active=True,
            created_at=now,
            updated_at=now,
        )
        return p_id

    async def update_as2_partnership(
        self, tenant_id: str, partnership_id: str, cmd: UpdateAS2PartnershipCmd
    ) -> bool:
        if (
            partnership_id in self.partnerships
            and self.partnerships[partnership_id].tenant_id == tenant_id
        ):
            p = self.partnerships[partnership_id]
            if not isinstance(cmd.active, type(UNSET)):
                p.active = bool(cmd.active)
            return True
        return False

    async def delete_as2_partnership(self, tenant_id: str, partnership_id: str) -> None:
        if (
            partnership_id in self.partnerships
            and self.partnerships[partnership_id].tenant_id == tenant_id
        ):
            del self.partnerships[partnership_id]

    async def get_as2_partnership(self, tenant_id: str, partnership_id: str) -> object | None:
        p = self.partnerships.get(partnership_id)
        return p if p and getattr(p, "tenant_id", None) == tenant_id else None

    async def list_as2_partnerships(self, tenant_id: str) -> list[object]:
        return [p for p in self.partnerships.values() if getattr(p, "tenant_id", None) == tenant_id]

    async def list_partnerships(self) -> list[object]:
        return list(self.partnerships.values())

    async def get_partnership_by_as2_ids(self, as2_from: str, as2_to: str) -> object | None:
        matches = []
        for partnership in self.partnerships.values():
            local_partner = self.partners_repo.partners.get(partnership.local_partner_id)
            remote_partner = self.partners_repo.partners.get(partnership.remote_partner_id)
            if (
                isinstance(local_partner, AS2PartnerDomainModel)
                and isinstance(remote_partner, AS2PartnerDomainModel)
                and partnership.active
                and local_partner.active
                and remote_partner.active
                and local_partner.as2_id.lower() == as2_to.lower()
                and remote_partner.as2_id.lower() == as2_from.lower()
                and partnership.tenant_id == local_partner.tenant_id == remote_partner.tenant_id
            ):
                matches.append((partnership, local_partner, remote_partner))
        if len(matches) != 1:
            return None
        return matches[0]

    async def save(self, aggregate: AggregateRoot) -> None:
        if isinstance(aggregate, AS2PartnershipDomainModel):
            self.partnerships[aggregate.id] = aggregate
        self._flush_events(aggregate)

    async def delete(self, aggregate: AggregateRoot) -> None:
        if isinstance(aggregate, AS2PartnershipDomainModel):
            self.partnerships.pop(aggregate.id, None)
        self._flush_events(aggregate)

    def _flush_events(self, aggregate: AggregateRoot):
        for event in aggregate.domain_events:
            self.outbox.append(
                OutboxEvent(
                    id=generate_id(SystemIdPrefix.GENERIC),
                    tenant_id=str(
                        getattr(event, "get_routing_tenant_id", lambda: None)()
                        or getattr(aggregate, "tenant_id", PLATFORM_TENANT_ID)
                    ),
                    event_type=str(getattr(event, "event_name", type(event).__name__)),
                    payload=serialize_domain_event(event),
                    idempotency_key=getattr(event, "idempotency_key", None),
                )
            )
        aggregate.clear_domain_events()


class FakeWebhookRepository:
    def __init__(self, outbox: FakeOutboxBase) -> None:
        self.webhooks: dict[str, WebhookDomainModel] = {}
        self.outbox = outbox

    async def list_webhooks(self, tenant_id: str) -> Sequence[object]:
        return [p for p in self.webhooks.values() if getattr(p, "tenant_id", None) == tenant_id]

    async def get_webhook(self, tenant_id: str, partner_id: str) -> object | None:
        p = self.webhooks.get(partner_id)
        return p if p and getattr(p, "tenant_id", None) == tenant_id else None

    async def get_webhooks_by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, str]:
        return {
            id: self.webhooks[id].name
            for id in ids
            if id in self.webhooks and self.webhooks[id].tenant_id == str(tenant_id)
        }


class FakeControlPlaneOutboxRepository:
    def __init__(self, outbox: FakeOutboxBase) -> None:
        self.outbox = outbox
        self._reservations: dict[str, dict[str, JsonValue]] = {}

    async def publish_outbox_event(self, event: object, idempotency_key: str | None = None) -> str:
        key = idempotency_key or generate_id(SystemIdPrefix.GENERIC)
        existing = next((e for e in self.outbox.outbox_events if e.idempotency_key == key), None)
        if existing:
            raise ValueError(f"Idempotency key {key} already exists")

        evt = OutboxEvent(
            id=generate_id(SystemIdPrefix.GENERIC),
            tenant_id=getattr(event, "tenant_id", PLATFORM_TENANT_ID),
            event_type=getattr(event, "event_type", type(event).__name__),
            payload=serialize_domain_event(event),
            idempotency_key=key,
        )
        self.outbox.append(evt)
        return key

    async def create_reservation(
        self, tenant_id: str, idempotency_key: str, fingerprint: str
    ) -> None:
        if idempotency_key in self._reservations:
            raise IdempotencyConflictError() from DuplicateEntityError(
                "Idempotency key already exists"
            )
        self._reservations[idempotency_key] = {
            "tenant_id": tenant_id,
            "idempotency_key": idempotency_key,
            "status": "RESERVED",
            "payload": {"fingerprint": fingerprint},
        }

    async def get_event_by_idempotency_key(self, idempotency_key: str) -> object | None:
        return self._reservations.get(idempotency_key)


class FakeOutboundEdiHeaderRepository:
    def __init__(self, outbox: FakeOutboxBase) -> None:
        self._edi_headers: dict[str, OutboundEdiHeaderDomainModel] = {}
        self.outbox = outbox

    async def get_outbound_edi_headers(self, tenant_id: str) -> Sequence[object]:
        return [h for h in self._edi_headers.values() if getattr(h, "tenant_id", None) == tenant_id]

    async def get_outbound_edi_header(self, tenant_id: str, header_id: str) -> object | None:
        h = self._edi_headers.get(header_id)
        return h if h and getattr(h, "tenant_id", None) == tenant_id else None

    async def get_outbound_edi_header_by_trading_partner_id(
        self, tenant_id: str, trading_partner_id: str
    ) -> object | None:
        for h in self._edi_headers.values():
            if h.tenant_id == tenant_id and h.trading_partner_id == trading_partner_id:
                return h
        return None

    async def save(self, aggregate: AggregateRoot) -> None:
        if isinstance(aggregate, OutboundEdiHeaderDomainModel):
            self._edi_headers[aggregate.id] = aggregate
        self._flush_events(aggregate)

    async def delete(self, aggregate: AggregateRoot) -> None:
        if isinstance(aggregate, OutboundEdiHeaderDomainModel):
            self._edi_headers.pop(aggregate.id, None)
        self._flush_events(aggregate)

    def _flush_events(self, aggregate: AggregateRoot):
        for event in aggregate.domain_events:
            self.outbox.append(
                OutboxEvent(
                    id=generate_id(SystemIdPrefix.GENERIC),
                    tenant_id=str(
                        getattr(event, "get_routing_tenant_id", lambda: None)()
                        or getattr(aggregate, "tenant_id", PLATFORM_TENANT_ID)
                    ),
                    event_type=str(getattr(event, "event_name", type(event).__name__)),
                    payload=serialize_domain_event(event),
                    idempotency_key=getattr(event, "idempotency_key", None),
                )
            )
        aggregate.clear_domain_events()


class FakeRoute:
    def __init__(
        self, id: str, tenant_id: str, cmd: CreateInboundRouteCmd | CreateOutboundRouteCmd
    ) -> None:
        self.id = id
        self.tenant_id = tenant_id
        self.name = cmd.name
        self.active = True
        self.as2_partner_id = cmd.as2_partner_id
        self.sftp_partner_id = cmd.sftp_partner_id
        if isinstance(cmd, CreateInboundRouteCmd):
            self.webhook_id = cmd.webhook_id
            self.processing_mode = cmd.processing_mode
            self.isa_sender_id = cmd.isa_sender_id
            self.isa_receiver_id = cmd.isa_receiver_id
            self.gs_sender_id = cmd.gs_sender_id
            self.gs_receiver_id = cmd.gs_receiver_id
            self.transaction_type = cmd.transaction_type
            self.direction = "INBOUND"
            self.trading_partner_id = None
            self.protocol = None
        else:
            self.webhook_id = None
            self.processing_mode = "TRANSFORM"
            self.isa_sender_id = "S1"
            self.isa_receiver_id = "R1"
            self.gs_sender_id = "S1"
            self.gs_receiver_id = "R1"
            self.transaction_type = "*"
            self.trading_partner_id = cmd.trading_partner_id
            self.direction = "OUTBOUND"
            self.protocol = cmd.protocol

        self.created_at = None
        self.updated_at = None
        self.default_standard = "x12"
        self.default_version = "004010"
        self.destination_name = None

    def __getitem__(self, key: str) -> object:
        return getattr(self, key)


class FakeTenantStore:
    def __init__(self) -> None:
        self.inbound_routes: dict[str, FakeRoute] = {}
        self.outbound_routes: dict[str, FakeRoute] = {}
        self.sftp_partners: list[dict[str, CreateSFTPPartnerCmd | str]] = []
        self.webhooks: list[dict[str, object]] = []

    async def create_inbound_route(self, cmd: CreateInboundRouteCmd) -> str:
        r_id = generate_id(SystemIdPrefix.GENERIC)
        self.inbound_routes[r_id] = FakeRoute(r_id, "1", cmd)
        return r_id

    async def create_outbound_route(self, cmd: CreateOutboundRouteCmd) -> str:
        r_id = generate_id(SystemIdPrefix.GENERIC)
        self.outbound_routes[r_id] = FakeRoute(r_id, "1", cmd)
        return r_id

    async def get_all_routes(self) -> dict[str, list[object]]:
        return {
            "inbound": list(self.inbound_routes.values()),
            "outbound": list(self.outbound_routes.values()),
        }

    async def create_sftp_partner(self, cmd: CreateSFTPPartnerCmd) -> str:
        p_id = generate_id(SystemIdPrefix.GENERIC)
        self.sftp_partners.append({"id": p_id, "cmd": cmd})
        return p_id

    async def get_sftp_partner(self, partner_id: str) -> object | None:
        for p in self.sftp_partners:
            if p["id"] == partner_id:
                cmd = p["cmd"]

                class MockPartner:
                    id = p["id"]
                    tenant_id = "1"
                    name = cmd.name if isinstance(cmd, CreateSFTPPartnerCmd) else str(cmd)
                    active = True

                return MockPartner()
        return None

    async def list_sftp_partners(self) -> Sequence[object]:
        return self.sftp_partners

    async def get_sftp_partners_by_ids(self, ids: list[str]) -> dict[str, str]:
        return {
            str(p["id"]): str(getattr(p["cmd"], "name", "unknown"))
            for p in self.sftp_partners
            if str(p["id"]) in ids
        }

    async def list_webhooks(self) -> Sequence[object]:
        return self.webhooks

    async def get_webhooks_by_ids(self, ids: list[str]) -> dict[str, str]:
        return {
            str(p["id"]): str(getattr(p["cmd"], "name", "unknown"))
            for p in self.webhooks
            if str(p["id"]) in ids
        }


class FakeTenantRepository(TenantRepositoryPort):
    def __init__(self) -> None:
        self.flags: dict[str, dict[str, JsonValue]] = {}

    async def get_tenant_flags(self, tenant_id: str) -> dict[str, JsonValue] | None:
        return self.flags.get(tenant_id)

    async def get_tenant(self, tenant_id: str) -> dict[str, JsonValue] | None:
        return None


class MockResult:
    def __init__(self, items: list[object]) -> None:
        self.items = items

    def scalars(self) -> "MockResult":
        return self

    def all(self) -> list[object]:
        return self.items


class MockSession:
    def __init__(self) -> None:
        pass

    async def execute(self, statement: object, params: dict | None = None) -> MockResult:
        return MockResult([])


class FakeControlPlaneUnitOfWork:
    def __init__(self) -> None:
        outbox = FakeOutboxBase()
        self.api_tokens = FakeTenantRepository()
        self.as2_partners = FakeAS2PartnerRepository(outbox)
        self.as2_partnerships = FakeAS2PartnershipRepository(outbox, self.as2_partners)
        self.inbound_routes = FakeInboundRouteRepository(outbox)
        self.outbound_routes = FakeOutboundRouteRepository(outbox)
        self.control_plane_outbox = FakeControlPlaneOutboxRepository(outbox)
        self.sftp_partners = FakeSFTPPartnerRepository(outbox)
        self.tenants = FakeTenantRepository()
        self.webhooks = FakeWebhookRepository(outbox)
        self.edi_headers = FakeOutboundEdiHeaderRepository(outbox)
        self.global_session = MockSession()

    async def __aenter__(self) -> "FakeControlPlaneUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: object | None,
    ) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class FakeDataPlaneUnitOfWork:
    def __init__(self) -> None:
        self.transactions = FakeTenantStore()
        outbox = FakeOutboxBase()
        self.data_plane_outbox = FakeControlPlaneOutboxRepository(
            outbox
        )  # Using the same for now to mock publish_outbox_event
        self.tenant_session = MockSession()

    async def __aenter__(self) -> "FakeDataPlaneUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: object | None,
    ) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass
