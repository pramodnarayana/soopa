from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TypeVar

from database.exceptions import DuplicateEntityError
from database.outbox_serializer import serialize_domain_event
from identity.domain.identity_context import PLATFORM_TENANT_ID
from seedwork.domain.aggregate import AggregateRoot
from seedwork.domain.types import UNSET
from seedwork.events import EventEnvelope
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from edi.application.use_cases.as2_partners.create_as2_partner_use_case import (
    CreateAS2TradingPartnerCmd,
)
from edi.application.use_cases.as2_partners.update_as2_partner_use_case import (
    UpdateAS2TradingPartnerCmd,
)
from edi.application.use_cases.as2_partnerships.create_as2_partnership_use_case import (
    CreateAS2PartnershipCmd,
)
from edi.application.use_cases.as2_partnerships.update_as2_partnership_use_case import (
    UpdateAS2PartnershipCmd,
)
from edi.application.use_cases.inbound_routes.create_inbound_route_use_case import (
    CreateInboundRouteCmd,
)
from edi.application.use_cases.inbound_routes.update_inbound_route_use_case import (
    UpdateInboundRouteCmd,
)
from edi.application.use_cases.outbound_routes.create_outbound_route_use_case import (
    CreateOutboundRouteCmd,
)
from edi.application.use_cases.outbound_routes.update_outbound_route_use_case import (
    UpdateOutboundRouteCmd,
)
from edi.application.use_cases.sftp_partners.create_sftp_partner_use_case import (
    CreateSFTPPartnerCmd,
)
from edi.application.use_cases.sftp_partners.update_sftp_partner_use_case import (
    UpdateSFTPPartnerCmd,
)
from edi.domain.authorization.tenant import TenantFeatureFlags, TenantSummary
from edi.domain.events import OutboxEvent
from edi.domain.exceptions import IdempotencyConflictError, PartnerAlreadyExistsError
from edi.domain.partner.as2.partner import AS2Partner
from edi.domain.partner.as2.partnership import AS2Partnership
from edi.domain.partner.sftp.partner import SFTPPartner
from edi.domain.routing.enums import ProcessingMode
from edi.domain.routing.inbound_route import InboundRoute
from edi.domain.routing.outbound_header import OutboundEdiHeader
from edi.domain.routing.outbound_route import OutboundRoute
from edi.domain.routing.webhook import Webhook
from edi.ports.outbound.tenant_repository import TenantRepositoryPort

T = TypeVar("T")


class FakeOutboxBase:
    """Shared outbox store across repositories within a UOW to accumulate events."""

    def __init__(self) -> None:
        self.outbox_events: list[OutboxEvent] = []
        self.reservations: dict[str, OutboxEvent] = {}

    def append(self, event: OutboxEvent) -> None:
        if event.idempotency_key and event.idempotency_key in self.reservations:
            reserved = self.reservations.pop(event.idempotency_key)
            base_payload = reserved.payload if isinstance(reserved.payload, dict) else {}
            next_payload = event.payload if isinstance(event.payload, dict) else {}
            event = OutboxEvent(
                id=reserved.id,
                tenant_id=event.tenant_id,
                event_type=event.event_type,
                payload={**base_payload, **next_payload},
                idempotency_key=event.idempotency_key,
            )
        self.outbox_events.append(event)


class FakeInboundRouteRepository:
    def __init__(self, outbox: FakeOutboxBase) -> None:
        self.inbound_routes: dict[str, InboundRoute] = {}
        self.outbox = outbox

    async def get_inbound_routes(self, tenant_id: str) -> list[object]:
        return [r for r in self.inbound_routes.values() if r.tenant_id == tenant_id]

    async def get_inbound_route(
        self,
        isa_sender_id: str,
        isa_receiver_id: str,
        tenant_id: str,
        transaction_type: str | None = None,
    ) -> InboundRoute | None:
        candidates = [
            r
            for r in self.inbound_routes.values()
            if r.tenant_id == tenant_id
            and r.isa_sender_id == isa_sender_id
            and r.isa_receiver_id == isa_receiver_id
            and r.active
        ]
        if transaction_type:
            exact = next((r for r in candidates if r.transaction_type == transaction_type), None)
            if exact is not None:
                return exact
            return next((r for r in candidates if r.transaction_type == "*"), None)
        return next((r for r in candidates if r.transaction_type is None), None)

    async def get_inbound_route_by_id(self, tenant_id: str, route_id: str) -> InboundRoute | None:
        route = self.inbound_routes.get(route_id)
        return route if route and route.tenant_id == tenant_id else None

    async def create_inbound_route(self, tenant_id: str, cmd: CreateInboundRouteCmd) -> str:
        r_id = generate_id(SystemIdPrefix.GENERIC)
        now = datetime.now(UTC).replace(tzinfo=None)
        pm = (
            ProcessingMode(cmd.processing_mode) if cmd.processing_mode else ProcessingMode.TRANSFORM
        )
        self.inbound_routes[r_id] = InboundRoute(
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

    async def list_inbound_routes(self, tenant_id: str) -> list[InboundRoute]:
        return [r for r in self.inbound_routes.values() if r.tenant_id == tenant_id]

    async def get_tenant_by_isa(self, isa_sender_id: str, isa_receiver_id: str) -> str | None:
        for r in self.inbound_routes.values():
            if r.isa_sender_id == isa_sender_id and r.isa_receiver_id == isa_receiver_id:
                return r.tenant_id
        return None

    async def save(self, aggregate: AggregateRoot) -> list[EventEnvelope]:
        if isinstance(aggregate, InboundRoute):
            self.inbound_routes[aggregate.id] = aggregate
        self._flush_events(aggregate)
        return []

    async def delete(self, aggregate: AggregateRoot) -> None:
        if isinstance(aggregate, InboundRoute):
            self.inbound_routes.pop(aggregate.id, None)
        self._flush_events(aggregate)

    def _flush_events(self, aggregate: AggregateRoot) -> list[EventEnvelope]:
        for event in aggregate.domain_events:
            self.outbox.append(
                OutboxEvent(
                    id=generate_id(SystemIdPrefix.GENERIC),
                    tenant_id=str(event.get_routing_tenant_id() or PLATFORM_TENANT_ID),
                    event_type=str(event.event_name),
                    payload=serialize_domain_event(event),
                    idempotency_key=event.idempotency_key,
                )
            )
        aggregate.clear_domain_events()
        return []


class FakeOutboundRouteRepository:
    def __init__(self, outbox: FakeOutboxBase) -> None:
        self.outbound_routes: dict[str, OutboundRoute] = {}
        self.outbox = outbox

    async def get_outbound_routes(self, tenant_id: str) -> list[object]:
        return [r for r in self.outbound_routes.values() if r.tenant_id == tenant_id]

    async def get_outbound_route(self, tenant_id: str, route_id: str) -> OutboundRoute | None:
        route = self.outbound_routes.get(route_id)
        return route if route and route.tenant_id == tenant_id else None

    async def get_outbound_route_by_trading_partner_id(
        self, tenant_id: str, trading_partner_id: str
    ) -> OutboundRoute | None:
        return next(
            (
                r
                for r in self.outbound_routes.values()
                if r.tenant_id == tenant_id and r.trading_partner_id == trading_partner_id
            ),
            None,
        )

    async def create_outbound_route(self, tenant_id: str, cmd: CreateOutboundRouteCmd) -> str:
        r_id = generate_id(SystemIdPrefix.GENERIC)
        now = datetime.now(UTC).replace(tzinfo=None)
        self.outbound_routes[r_id] = OutboundRoute(
            id=r_id,
            tenant_id=tenant_id,
            name=cmd.name,
            active=True,
            trading_partner_id=cmd.trading_partner_id,
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

    async def list_outbound_routes(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> Sequence[OutboundRoute]:
        results = [r for r in self.outbound_routes.values() if r.tenant_id == tenant_id]
        return results[offset : offset + limit]

    async def save(self, aggregate: AggregateRoot) -> list[EventEnvelope]:
        if isinstance(aggregate, OutboundRoute):
            self.outbound_routes[aggregate.id] = aggregate
        self._flush_events(aggregate)
        return []

    async def delete(self, aggregate: AggregateRoot) -> None:
        if isinstance(aggregate, OutboundRoute):
            self.outbound_routes.pop(aggregate.id, None)
        self._flush_events(aggregate)

    def _flush_events(self, aggregate: AggregateRoot) -> list[EventEnvelope]:
        for event in aggregate.domain_events:
            self.outbox.append(
                OutboxEvent(
                    id=generate_id(SystemIdPrefix.GENERIC),
                    tenant_id=str(event.get_routing_tenant_id() or PLATFORM_TENANT_ID),
                    event_type=str(event.event_name),
                    payload=serialize_domain_event(event),
                    idempotency_key=event.idempotency_key,
                )
            )
        aggregate.clear_domain_events()
        return []


class FakeAS2PartnerRepository:
    def __init__(self, outbox: FakeOutboxBase) -> None:
        self.partners: dict[str, AS2Partner] = {}
        self.outbox = outbox

    async def create_as2_identity(self, tenant_id: str, cmd: CreateAS2TradingPartnerCmd) -> str:
        for p in self.partners.values():
            if (
                isinstance(p, AS2Partner)
                and p.tenant_id == str(tenant_id)
                and p.as2_id == cmd.as2_id
            ):
                raise PartnerAlreadyExistsError(as2_id=cmd.as2_id, tenant_id=str(tenant_id))
        partner_id = generate_id(SystemIdPrefix.GENERIC)
        now = datetime.now(UTC).replace(tzinfo=None)
        aggregate = AS2Partner(
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
            if isinstance(cmd.name, str):
                p.name = cmd.name

    async def delete_as2_identity(self, tenant_id: str, partner_id: str) -> None:
        if partner_id in self.partners and self.partners[partner_id].tenant_id == tenant_id:
            del self.partners[partner_id]

    async def get_as2_partner(self, tenant_id: str, partner_id: str) -> AS2Partner | None:
        p = self.partners.get(partner_id)
        return p if p and p.tenant_id in (PLATFORM_TENANT_ID, str(tenant_id)) else None

    async def get_as2_partner_by_as2_id(self, tenant_id: str, as2_id: str) -> AS2Partner | None:
        return next(
            (
                p
                for p in self.partners.values()
                if p.tenant_id in (PLATFORM_TENANT_ID, str(tenant_id)) and p.as2_id == as2_id
            ),
            None,
        )

    async def update_partner_status(self, tenant_id: str, partner_id: str, status: str) -> None:
        if partner_id in self.partners and self.partners[partner_id].tenant_id == tenant_id:
            self.partners[partner_id].active = status == "ACTIVE"

    async def list_trading_partners(self) -> list[object]:
        return list(self.partners.values())

    async def list_as2_partners(self, tenant_id: str) -> Sequence[AS2Partner]:
        return [
            p for p in self.partners.values() if p.tenant_id in (PLATFORM_TENANT_ID, str(tenant_id))
        ]

    async def get_as2_partners_by_ids(self, tenant_id: str, ids: list[str]) -> list[AS2Partner]:
        return [
            self.partners[id]
            for id in ids
            if id in self.partners
            and self.partners[id].tenant_id in (PLATFORM_TENANT_ID, str(tenant_id))
        ]

    async def is_vault_ref_in_use(self, tenant_id: str, vault_ref: str = "") -> bool:
        effective_ref = vault_ref or tenant_id
        for p in self.partners.values():
            if isinstance(p, AS2Partner) and (
                p.private_key_vault_ref == effective_ref or p.public_cert_vault_ref == effective_ref
            ):
                return True
        return False

    async def save(self, aggregate: AggregateRoot) -> list[EventEnvelope]:
        if isinstance(aggregate, AS2Partner):
            for existing in self.partners.values():
                if (
                    isinstance(existing, AS2Partner)
                    and existing.id != aggregate.id
                    and existing.tenant_id == aggregate.tenant_id
                    and existing.as2_id == aggregate.as2_id
                ):
                    raise PartnerAlreadyExistsError(
                        as2_id=aggregate.as2_id, tenant_id=aggregate.tenant_id or PLATFORM_TENANT_ID
                    )
            self.partners[aggregate.id] = aggregate
        self._flush_events(aggregate)
        return []

    async def delete(self, aggregate: AggregateRoot) -> None:
        if isinstance(aggregate, AS2Partner):
            self.partners.pop(aggregate.id, None)
        self._flush_events(aggregate)

    def _flush_events(self, aggregate: AggregateRoot) -> list[EventEnvelope]:
        for event in aggregate.domain_events:
            self.outbox.append(
                OutboxEvent(
                    id=generate_id(SystemIdPrefix.GENERIC),
                    tenant_id=str(event.get_routing_tenant_id() or PLATFORM_TENANT_ID),
                    event_type=str(event.event_name),
                    payload=serialize_domain_event(event),
                    idempotency_key=event.idempotency_key,
                )
            )
        aggregate.clear_domain_events()
        return []


class FakeSFTPPartnerRepository:
    def __init__(self, outbox: FakeOutboxBase) -> None:
        self.sftp_partners: dict[str, SFTPPartner] = {}
        self.outbox = outbox

    async def create_sftp_partner(self, tenant_id: str, cmd: CreateSFTPPartnerCmd) -> str:
        partner_id = generate_id(SystemIdPrefix.GENERIC)
        now = datetime.now(UTC).replace(tzinfo=None)
        aggregate = SFTPPartner(
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

    async def get_sftp_partner(self, tenant_id: str, partner_id: str) -> SFTPPartner | None:
        p = self.sftp_partners.get(partner_id)
        return p if p and p.tenant_id == tenant_id else None

    async def list_sftp_partners(self, tenant_id: str) -> Sequence[SFTPPartner]:
        return [p for p in self.sftp_partners.values() if p.tenant_id == tenant_id]

    async def get_sftp_partners_by_ids(self, tenant_id: str, ids: list[str]) -> list[SFTPPartner]:
        return [
            self.sftp_partners[id]
            for id in ids
            if id in self.sftp_partners and self.sftp_partners[id].tenant_id == str(tenant_id)
        ]

    async def save(self, aggregate: AggregateRoot) -> list[EventEnvelope]:
        if isinstance(aggregate, SFTPPartner):
            self.sftp_partners[aggregate.id] = aggregate
        self._flush_events(aggregate)
        return []

    async def delete(self, aggregate: AggregateRoot) -> None:
        if isinstance(aggregate, SFTPPartner):
            self.sftp_partners.pop(aggregate.id, None)
        self._flush_events(aggregate)

    def _flush_events(self, aggregate: AggregateRoot) -> list[EventEnvelope]:
        for event in aggregate.domain_events:
            self.outbox.append(
                OutboxEvent(
                    id=generate_id(SystemIdPrefix.GENERIC),
                    tenant_id=str(event.get_routing_tenant_id() or PLATFORM_TENANT_ID),
                    event_type=str(event.event_name),
                    payload=serialize_domain_event(event),
                    idempotency_key=event.idempotency_key,
                )
            )
        aggregate.clear_domain_events()
        return []


class FakeAS2PartnershipRepository:
    def __init__(self, outbox: FakeOutboxBase, partners_repo: FakeAS2PartnerRepository) -> None:
        self.partnerships: dict[str, AS2Partnership] = {}
        self.outbox = outbox
        self.partners_repo = partners_repo

    async def create_as2_partnership(self, tenant_id: str, cmd: CreateAS2PartnershipCmd) -> str:
        p_id = generate_id(SystemIdPrefix.GENERIC)
        now = datetime.now(UTC).replace(tzinfo=None)
        self.partnerships[p_id] = AS2Partnership(
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
        return p if p and p.tenant_id == tenant_id else None

    async def list_as2_partnerships(self, tenant_id: str) -> list[object]:
        return [p for p in self.partnerships.values() if p.tenant_id == tenant_id]

    async def list_partnerships(self) -> list[object]:
        return list(self.partnerships.values())

    async def get_partnership_by_as2_ids(self, as2_from: str, as2_to: str) -> object | None:
        matches = []
        for partnership in self.partnerships.values():
            local_partner = self.partners_repo.partners.get(partnership.local_partner_id)
            remote_partner = self.partners_repo.partners.get(partnership.remote_partner_id)
            if (
                isinstance(local_partner, AS2Partner)
                and isinstance(remote_partner, AS2Partner)
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

    async def save(self, aggregate: AggregateRoot) -> list[EventEnvelope]:
        if isinstance(aggregate, AS2Partnership):
            self.partnerships[aggregate.id] = aggregate
        self._flush_events(aggregate)
        return []

    async def delete(self, aggregate: AggregateRoot) -> None:
        if isinstance(aggregate, AS2Partnership):
            self.partnerships.pop(aggregate.id, None)
        self._flush_events(aggregate)

    def _flush_events(self, aggregate: AggregateRoot) -> list[EventEnvelope]:
        for event in aggregate.domain_events:
            self.outbox.append(
                OutboxEvent(
                    id=generate_id(SystemIdPrefix.GENERIC),
                    tenant_id=str(event.get_routing_tenant_id() or PLATFORM_TENANT_ID),
                    event_type=str(event.event_name),
                    payload=serialize_domain_event(event),
                    idempotency_key=event.idempotency_key,
                )
            )
        aggregate.clear_domain_events()
        return []


class FakeWebhookRepository:
    def __init__(self, outbox: FakeOutboxBase) -> None:
        self.webhooks: dict[str, Webhook] = {}
        self.outbox = outbox

    async def list_webhooks(self, tenant_id: str) -> Sequence[Webhook]:
        return [p for p in self.webhooks.values() if p.tenant_id == tenant_id]

    async def get_webhook(self, tenant_id: str, webhook_id: str) -> Webhook | None:
        p = self.webhooks.get(webhook_id)
        return p if p and p.tenant_id == tenant_id else None

    async def get_webhooks_by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, str]:
        return {
            id: self.webhooks[id].name
            for id in ids
            if id in self.webhooks and self.webhooks[id].tenant_id == str(tenant_id)
        }


class FakeControlPlaneOutboxRepository:
    def __init__(self, outbox: FakeOutboxBase) -> None:
        self.outbox = outbox

    async def create_reservation(
        self, tenant_id: str, idempotency_key: str, fingerprint: str
    ) -> None:
        if idempotency_key in self.outbox.reservations or any(
            e.idempotency_key == idempotency_key for e in self.outbox.outbox_events
        ):
            raise IdempotencyConflictError() from DuplicateEntityError(
                "Idempotency key already exists"
            )
        self.outbox.reservations[idempotency_key] = OutboxEvent(
            id=f"reservation_{idempotency_key}",
            tenant_id=tenant_id,
            event_type="RESERVATION",
            payload={"fingerprint": fingerprint},
            idempotency_key=idempotency_key,
        )

    async def get_event_by_idempotency_key(self, idempotency_key: str) -> OutboxEvent | None:
        if idempotency_key in self.outbox.reservations:
            return self.outbox.reservations[idempotency_key]
        return next(
            (e for e in self.outbox.outbox_events if e.idempotency_key == idempotency_key), None
        )


class FakeOutboundEdiHeaderRepository:
    def __init__(self, outbox: FakeOutboxBase) -> None:
        self._edi_headers: dict[str, OutboundEdiHeader] = {}
        self.outbox = outbox

    async def get_outbound_edi_headers(self, tenant_id: str) -> Sequence[object]:
        return [h for h in self._edi_headers.values() if h.tenant_id == tenant_id]

    async def get_outbound_edi_header(self, tenant_id: str, header_id: str) -> object | None:
        h = self._edi_headers.get(header_id)
        return h if h and h.tenant_id == tenant_id else None

    async def get_outbound_edi_header_by_trading_partner_id(
        self, tenant_id: str, trading_partner_id: str
    ) -> object | None:
        for h in self._edi_headers.values():
            if h.tenant_id == tenant_id and h.trading_partner_id == trading_partner_id:
                return h
        return None

    async def save(self, aggregate: AggregateRoot) -> list[EventEnvelope]:
        if isinstance(aggregate, OutboundEdiHeader):
            self._edi_headers[aggregate.id] = aggregate
        self._flush_events(aggregate)
        return []

    async def delete(self, aggregate: AggregateRoot) -> None:
        if isinstance(aggregate, OutboundEdiHeader):
            self._edi_headers.pop(aggregate.id, None)
        self._flush_events(aggregate)

    def _flush_events(self, aggregate: AggregateRoot) -> list[EventEnvelope]:
        for event in aggregate.domain_events:
            self.outbox.append(
                OutboxEvent(
                    id=generate_id(SystemIdPrefix.GENERIC),
                    tenant_id=str(event.get_routing_tenant_id() or PLATFORM_TENANT_ID),
                    event_type=str(event.event_name),
                    payload=serialize_domain_event(event),
                    idempotency_key=event.idempotency_key,
                )
            )
        aggregate.clear_domain_events()
        return []


class FakeTenantRepository(TenantRepositoryPort):
    def __init__(self) -> None:
        self.flags: dict[str, TenantFeatureFlags] = {}
        self.tenants: dict[str, TenantSummary] = {}

    async def get_tenant_flags(self, tenant_id: str) -> TenantFeatureFlags | None:
        return self.flags.get(tenant_id)

    async def get_tenant(self, tenant_id: str) -> TenantSummary | None:
        return self.tenants.get(tenant_id)


class FakeResult:
    def __init__(self, items: list[object]) -> None:
        self.items = items

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[object]:
        return self.items


class FakeSession:
    def __init__(self) -> None:
        pass

    async def execute(
        self, _statement: object, params: dict[str, object] | None = None
    ) -> FakeResult:
        return FakeResult([])


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
        self.global_session = FakeSession()

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
