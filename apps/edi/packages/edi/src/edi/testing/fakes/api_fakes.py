from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, TypeVar

from database.exceptions import DuplicateEntityError
from database.outbox_serializer import serialize_domain_event
from identity.domain.identity_context import PLATFORM_TENANT_ID
from seedwork.constants import SystemIdPrefix
from seedwork.utils import generate_id

from edi.application.dto import (
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
from edi.domain.models.sftp import SFTPPartnerDomainModel
from edi.ports.outbound.repository import (
    TenantRepositoryPort,
)

T = TypeVar("T")


class FakeGlobalStore:
    def __init__(self) -> None:
        self.partners: dict[str, Any] = {}
        self.partnerships: dict[str, Any] = {}
        self.sftp_partners: dict[str, Any] = {}
        self.webhooks: dict[str, Any] = {}
        self.outbox_events: list[Any] = []
        self.inbound_routes: dict[str, Any] = {}
        self.outbound_routes: dict[str, Any] = {}
        self._edi_headers: dict[str, Any] = {}

    async def get_inbound_routes(self, tenant_id: str) -> list[Any]:
        return [r for r in self.inbound_routes.values() if r.tenant_id == tenant_id]

    async def get_inbound_route(self, tenant_id: str, route_id: str) -> Any:
        route = self.inbound_routes.get(route_id)
        return route if route and route.tenant_id == tenant_id else None

    async def get_inbound_route_by_id(self, tenant_id: str, route_id: str) -> Any:
        return await self.get_inbound_route(tenant_id, route_id)

    async def get_outbound_routes(self, tenant_id: str) -> list[Any]:
        return [r for r in self.outbound_routes.values() if r.tenant_id == tenant_id]

    async def get_outbound_route(self, tenant_id: str, route_id: str) -> Any:
        route = self.outbound_routes.get(route_id)
        return route if route and route.tenant_id == tenant_id else None

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
            is_local=getattr(cmd, "is_local", False),
            url=getattr(cmd, "url", None),
            public_cert_pem=getattr(cmd, "public_cert_pem", None),
            public_cert_vault_ref=getattr(cmd, "public_cert_vault_ref", None),
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

    async def create_sftp_partner(self, tenant_id: str, cmd: CreateSFTPPartnerCmd) -> str:

        partner_id = generate_id(SystemIdPrefix.GENERIC)
        now = datetime.now(UTC).replace(tzinfo=None)
        aggregate = SFTPPartnerDomainModel(
            id=partner_id,
            tenant_id=str(tenant_id),
            name=cmd.name,
            host=cmd.host,
            port=getattr(cmd, "port", 22),
            username=cmd.username,
            inbound_remote_path=getattr(cmd, "inbound_remote_path", None),
            outbound_remote_path=getattr(cmd, "outbound_remote_path", None),
            credentials_vault_ref=getattr(cmd, "credentials_vault_ref", None),
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
                p.active = cmd.active
            return True
        return False

    async def delete_sftp_partner(self, tenant_id: str, partner_id: str) -> None:
        if (
            partner_id in self.sftp_partners
            and self.sftp_partners[partner_id].tenant_id == tenant_id
        ):
            del self.sftp_partners[partner_id]

    async def create_as2_partnership(self, tenant_id: str, cmd: CreateAS2PartnershipCmd) -> str:
        p_id = generate_id(SystemIdPrefix.GENERIC)

        class FakePartnership:
            id = p_id
            self_tenant_id = tenant_id
            name = cmd.name
            local_partner_id = cmd.local_partner_id
            remote_partner_id = cmd.remote_partner_id
            mdn_type = cmd.mdn_type
            mdn_url = cmd.mdn_url
            encryption_algorithm = cmd.encryption_algorithm
            signature_algorithm = cmd.signature_algorithm
            active = True

            @property
            def tenant_id(self) -> str:
                return self.self_tenant_id

        self.partnerships[p_id] = FakePartnership()
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
                p.active = cmd.active
            return True
        return False

    async def delete_as2_partnership(self, tenant_id: str, partnership_id: str) -> None:
        if (
            partnership_id in self.partnerships
            and self.partnerships[partnership_id].tenant_id == tenant_id
        ):
            del self.partnerships[partnership_id]

    async def get_as2_partner(self, tenant_id: str, partner_id: str) -> Any:
        p = self.partners.get(partner_id)
        return p if p and p.tenant_id == tenant_id else None

    async def get_as2_partnership(self, tenant_id: str, partnership_id: str) -> Any:
        p = self.partnerships.get(partnership_id)
        return p if p and p.tenant_id == tenant_id else None

    async def list_as2_partnerships(self, tenant_id: str) -> list[Any]:
        return [p for p in self.partnerships.values() if p.tenant_id == tenant_id]

    async def publish_outbox_event(
        self,
        event: Any,
        idempotency_key: str | None = None,
    ) -> str:
        key = idempotency_key or generate_id(SystemIdPrefix.GENERIC)
        existing = next((e for e in self.outbox_events if e.get("idempotency_key") == key), None)
        if existing:
            if existing.get("status") != "RESERVED":
                raise ValueError(f"Idempotency key {key} already exists")
            existing.update(
                {
                    "tenant_id": getattr(event, "tenant_id", None),
                    "event_type": getattr(event, "event_type", None),
                    "payload": {
                        **existing.get("payload", {}),
                        **serialize_domain_event(event),
                    },
                    "status": "PENDING",
                }
            )
            return key
        self.outbox_events.append(
            {
                "tenant_id": getattr(event, "tenant_id", None),
                "event_type": getattr(event, "event_type", None),
                "payload": serialize_domain_event(event),
                "idempotency_key": key,
            }
        )
        return key

    async def update_partner_status(self, tenant_id: str, partner_id: str, status: str) -> None:
        if partner_id in self.partners and self.partners[partner_id].tenant_id == tenant_id:
            self.partners[partner_id].active = status == "ACTIVE"

    async def list_trading_partners(self) -> list[Any]:
        return list(self.partners.values())

    async def list_as2_partners(self, tenant_id: str) -> Sequence[Any]:
        return [p for p in self.partners.values() if p.tenant_id == tenant_id]

    async def list_partnerships(self) -> list[Any]:
        return list(self.partnerships.values())

    async def get_as2_partners_by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, str]:
        return {
            id: self.partners[id].name
            for id in ids
            if id in self.partners and self.partners[id].tenant_id == str(tenant_id)
        }

    async def get_sftp_partners_by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, str]:
        return {
            id: self.sftp_partners[id].name
            for id in ids
            if id in self.sftp_partners and self.sftp_partners[id].tenant_id == str(tenant_id)
        }

    async def get_webhooks_by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, str]:
        return {
            id: self.webhooks[id].name
            for id in ids
            if id in self.webhooks and self.webhooks[id].tenant_id == str(tenant_id)
        }

    async def create_inbound_route(self, tenant_id: str, cmd: CreateInboundRouteCmd) -> str:
        r_id = generate_id(SystemIdPrefix.GENERIC)
        self.inbound_routes[r_id] = FakeRoute(r_id, tenant_id, cmd)
        return r_id

    async def create_outbound_route(self, tenant_id: str, cmd: CreateOutboundRouteCmd) -> str:
        r_id = generate_id(SystemIdPrefix.GENERIC)
        self.outbound_routes[r_id] = FakeRoute(r_id, tenant_id, cmd)
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

    async def list_inbound_routes(self, tenant_id: str) -> list[Any]:
        return [r for r in self.inbound_routes.values() if r.tenant_id == tenant_id]

    async def list_outbound_routes(self, tenant_id: str) -> list[Any]:
        return [r for r in self.outbound_routes.values() if r.tenant_id == tenant_id]

    async def list_sftp_partners(self, tenant_id: str) -> Sequence[Any]:
        return [p for p in self.sftp_partners.values() if p.tenant_id == tenant_id]

    async def list_webhooks(self, tenant_id: str) -> Sequence[Any]:
        return [p for p in self.webhooks.values() if p.tenant_id == tenant_id]

    async def get_sftp_partner(self, tenant_id: str, partner_id: str) -> Any:
        p = self.sftp_partners.get(partner_id)
        return p if p and p.tenant_id == tenant_id else None

    async def get_webhook(self, tenant_id: str, partner_id: str) -> Any:
        p = self.webhooks.get(partner_id)
        return p if p and p.tenant_id == tenant_id else None

    # ------------------------------------------------------------------
    # Aggregate save / delete — required by all refactored use cases
    # ------------------------------------------------------------------

    async def save(self, aggregate: Any) -> None:
        """Upsert aggregate into the appropriate in-memory store."""
        if isinstance(aggregate, AS2PartnerDomainModel):
            # Mirror real repository: raise PartnerAlreadyExistsError on duplicate as2_id
            for existing in self.partners.values():
                if (
                    isinstance(existing, AS2PartnerDomainModel)
                    and existing.id != aggregate.id
                    and existing.tenant_id == aggregate.tenant_id
                    and existing.as2_id == aggregate.as2_id
                ):
                    raise PartnerAlreadyExistsError(
                        as2_id=aggregate.as2_id,
                        tenant_id=aggregate.tenant_id or PLATFORM_TENANT_ID,
                    )
            self.partners[aggregate.id] = aggregate
        elif isinstance(aggregate, AS2PartnershipDomainModel):
            self.partnerships[aggregate.id] = aggregate
        elif isinstance(aggregate, SFTPPartnerDomainModel):
            self.sftp_partners[aggregate.id] = aggregate
        elif isinstance(aggregate, InboundRouteDomainModel):
            self.inbound_routes[aggregate.id] = aggregate
        elif isinstance(aggregate, OutboundRouteDomainModel):
            self.outbound_routes[aggregate.id] = aggregate
        elif isinstance(aggregate, OutboundEdiHeaderDomainModel):
            self._edi_headers[aggregate.id] = aggregate

        for event in aggregate.domain_events:
            self.outbox_events.append(
                {
                    "tenant_id": event.get_routing_tenant_id()
                    or getattr(aggregate, "tenant_id", None),
                    "event_type": event.event_name,
                    "payload": serialize_domain_event(event),
                    "idempotency_key": event.idempotency_key,
                }
            )
        aggregate.clear_domain_events()

    async def delete(self, aggregate: Any) -> None:
        """Remove aggregate from the appropriate in-memory store."""
        if isinstance(aggregate, AS2PartnerDomainModel):
            self.partners.pop(aggregate.id, None)
        elif isinstance(aggregate, AS2PartnershipDomainModel):
            self.partnerships.pop(aggregate.id, None)
        elif isinstance(aggregate, SFTPPartnerDomainModel):
            self.sftp_partners.pop(aggregate.id, None)
        elif isinstance(aggregate, InboundRouteDomainModel):
            self.inbound_routes.pop(aggregate.id, None)
        elif isinstance(aggregate, OutboundRouteDomainModel):
            self.outbound_routes.pop(aggregate.id, None)
        elif isinstance(aggregate, OutboundEdiHeaderDomainModel):
            self._edi_headers.pop(aggregate.id, None)

        for event in aggregate.domain_events:
            self.outbox_events.append(
                {
                    "tenant_id": event.get_routing_tenant_id()
                    or getattr(aggregate, "tenant_id", None),
                    "event_type": event.event_name,
                    "payload": serialize_domain_event(event),
                    "idempotency_key": event.idempotency_key,
                }
            )
        aggregate.clear_domain_events()

    async def is_vault_ref_in_use(self, vault_ref: str) -> bool:
        for p in self.partners.values():
            if isinstance(p, AS2PartnerDomainModel) and (
                getattr(p, "private_key_vault_ref", None) == vault_ref
                or getattr(p, "public_cert_vault_ref", None) == vault_ref
            ):
                return True
        return False

    async def get_partnership_by_as2_ids(self, as2_from: str, as2_to: str) -> Any:
        matches = []
        for partnership in self.partnerships.values():
            local_partner = self.partners.get(partnership.local_partner_id)
            remote_partner = self.partners.get(partnership.remote_partner_id)
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

    async def get_tenant_by_isa(self, isa_sender_id: str, isa_receiver_id: str) -> str | None:
        for r in self.inbound_routes.values():
            if (
                getattr(r, "isa_sender_id", None) == isa_sender_id
                and getattr(r, "isa_receiver_id", None) == isa_receiver_id
            ):
                return getattr(r, "tenant_id", None)
        return None

    async def get_outbound_edi_headers(self, tenant_id: str) -> Sequence[Any]:
        return [h for h in self._edi_headers.values() if h.tenant_id == tenant_id]

    async def get_outbound_edi_header(self, tenant_id: str, header_id: str) -> Any:
        h = self._edi_headers.get(header_id)
        return h if h and h.tenant_id == tenant_id else None

    async def get_outbound_edi_header_by_trading_partner_id(
        self, tenant_id: str, trading_partner_id: str
    ) -> Any:
        for h in self._edi_headers.values():
            if h.tenant_id == tenant_id and h.trading_partner_id == trading_partner_id:
                return h
        return None

    async def create_reservation(
        self, tenant_id: str, idempotency_key: str, fingerprint: str
    ) -> None:

        if any(e.get("idempotency_key") == idempotency_key for e in self.outbox_events):
            raise IdempotencyConflictError() from DuplicateEntityError(
                "Idempotency key already exists"
            )
        self.outbox_events.append(
            {
                "tenant_id": tenant_id,
                "idempotency_key": idempotency_key,
                "status": "RESERVED",
                "payload": {"fingerprint": fingerprint},
            }
        )

    async def get_event_by_idempotency_key(self, idempotency_key: str) -> Any | None:
        for e in self.outbox_events:
            if e.get("idempotency_key") == idempotency_key:
                return e
        return None

    async def get_tenant_flags(self, tenant_id: str) -> dict[str, Any] | None:
        return None


class FakeRoute:
    def __init__(self, id: str, tenant_id: str, cmd: Any) -> None:
        self.id = id
        self.tenant_id = tenant_id
        self.name = getattr(cmd, "name", "Test Route")
        self.processing_mode = getattr(cmd, "processing_mode", "TRANSFORM")
        self.active = True
        self.as2_partner_id = getattr(cmd, "as2_partner_id", None)
        self.sftp_partner_id = getattr(cmd, "sftp_partner_id", None)
        self.webhook_id = getattr(cmd, "webhook_id", None)
        self.isa_sender_id = getattr(cmd, "isa_sender_id", "S1")
        self.isa_receiver_id = getattr(cmd, "isa_receiver_id", "R1")
        self.gs_sender_id = getattr(cmd, "gs_sender_id", "S1")
        self.gs_receiver_id = getattr(cmd, "gs_receiver_id", "R1")
        self.transaction_type = getattr(cmd, "transaction_type", "*")
        self.trading_partner_id = getattr(cmd, "trading_partner_id", None)
        self.created_at = None
        self.updated_at = None
        self.direction = "INBOUND" if isinstance(cmd, CreateInboundRouteCmd) else "OUTBOUND"
        self.default_standard = "x12"
        self.default_version = "004010"
        self.destination_name = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class FakeTenantStore:
    def __init__(self) -> None:
        self.inbound_routes: dict[str, Any] = {}
        self.outbound_routes: dict[str, Any] = {}
        self.sftp_partners: list[Any] = []
        self.webhooks: list[Any] = []

    async def create_inbound_route(self, cmd: CreateInboundRouteCmd) -> str:
        r_id = generate_id(SystemIdPrefix.GENERIC)
        self.inbound_routes[r_id] = FakeRoute(r_id, "1", cmd)
        return r_id

    async def create_outbound_route(self, cmd: CreateOutboundRouteCmd) -> str:
        r_id = generate_id(SystemIdPrefix.GENERIC)
        self.outbound_routes[r_id] = FakeRoute(r_id, "1", cmd)
        return r_id

    async def get_all_routes(self) -> dict[str, list[Any]]:
        return {
            "inbound": list(self.inbound_routes.values()),
            "outbound": list(self.outbound_routes.values()),
        }

    async def create_sftp_partner(self, cmd: CreateSFTPPartnerCmd) -> str:
        p_id = generate_id(SystemIdPrefix.GENERIC)
        self.sftp_partners.append({"id": p_id, "cmd": cmd})
        return p_id

    async def get_sftp_partner(self, partner_id: str) -> Any:
        for p in self.sftp_partners:
            if p["id"] == partner_id:

                class MockPartner:
                    id = p["id"]
                    tenant_id = "1"
                    name = p["cmd"].name
                    active = True

                return MockPartner()
        return None

    async def list_sftp_partners(self) -> Sequence[Any]:
        return self.sftp_partners

    async def get_sftp_partners_by_ids(self, ids: list[str]) -> dict[str, str]:
        return {p["id"]: p["cmd"].name for p in self.sftp_partners if p["id"] in ids}

    async def list_webhooks(self) -> Sequence[Any]:
        return self.webhooks

    async def get_webhooks_by_ids(self, ids: list[str]) -> dict[str, str]:
        return {p["id"]: p["cmd"].name for p in self.webhooks if p["id"] in ids}


class FakeTenantRepository(TenantRepositoryPort):
    def __init__(self) -> None:
        self.flags: dict[str, Any] = {}

    async def get_tenant_flags(self, tenant_id: str) -> dict[str, Any] | None:
        return self.flags.get(tenant_id)


class MockResult:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def scalars(self) -> Any:
        return self

    def all(self) -> list[Any]:
        return self.items


class MockSession:
    def __init__(self, global_store: Any) -> None:
        self.global_store = global_store

    async def execute(self, statement: Any) -> Any:
        return MockResult([])


class FakeControlPlaneUnitOfWork:
    def __init__(self) -> None:
        repo = FakeGlobalStore()
        self.api_tokens = repo
        self.as2_partners = repo
        self.as2_partnerships = repo
        self.inbound_routes = repo
        self.outbound_routes = repo
        self.control_plane_outbox = repo
        self.sftp_partners = repo
        self.tenants = repo
        self.webhooks = repo
        self.edi_headers = repo
        self.global_session = MockSession(repo)

    async def __aenter__(self) -> Any:
        return self

    async def __aexit__(self, exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class FakeDataPlaneUnitOfWork:
    def __init__(self) -> None:
        self.transactions = FakeTenantStore()
        repo = FakeGlobalStore()
        self.data_plane_outbox = self.transactions
        self.tenant_session = MockSession(repo)

    async def __aenter__(self) -> Any:
        return self

    async def __aexit__(self, exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass
