import uuid
from collections.abc import Sequence
from typing import Any

from api.domain.models import (
    CreateAS2PartnershipCmd,
    CreateAS2TradingPartnerCmd,
    CreateInboundRouteCmd,
    CreateOutboundRouteCmd,
    CreateSFTPPartnerCmd,
    CreateWebhookPartnerCmd,
)
from api.ports.repository import (
    ControlPlaneRepositoryPort,
    DataPlaneRepositoryPort,
    TenantRepositoryPort,
)


class FakeControlPlaneRepository(ControlPlaneRepositoryPort):
    def __init__(self):
        self.partners = []
        self.partnerships = []
        self.outbox_events = []

    async def create_as2_identity(
        self, tenant_id: int, cmd: CreateAS2TradingPartnerCmd
    ) -> uuid.UUID:
        p_id = uuid.uuid4()
        self.partners.append({"id": p_id, "tenant_id": tenant_id, "cmd": cmd})
        return p_id

    async def create_as2_partnership(
        self, tenant_id: int, cmd: CreateAS2PartnershipCmd
    ) -> uuid.UUID:
        p_id = uuid.uuid4()
        self.partnerships.append({"id": p_id, "tenant_id": tenant_id, "cmd": cmd})
        return p_id

    async def get_as2_partner(self, tenant_id: int, partner_id: uuid.UUID) -> Any:
        for p in self.partners:
            if p["id"] == partner_id and p["tenant_id"] == tenant_id:
                # Mock an AS2Partner DB object
                class FakePartner:
                    id = p["id"]
                    tenant_id = p["tenant_id"]
                    name = p["cmd"].name
                    as2_id = p["cmd"].as2_id
                    is_local = p["cmd"].is_local
                    url = p["cmd"].url
                    active = p.get("status", "INACTIVE") == "ACTIVE"

                return FakePartner()
        return None

    async def get_as2_partnership(self, tenant_id: int, partnership_id: uuid.UUID) -> Any:
        for p in self.partnerships:
            if p["id"] == partnership_id and p["tenant_id"] == tenant_id:

                class FakePartnership:
                    id = p["id"]
                    tenant_id = p["tenant_id"]
                    name = p["cmd"].name
                    local_partner_id = p["cmd"].local_partner_id
                    remote_partner_id = p["cmd"].remote_partner_id
                    mdn_type = p["cmd"].mdn_type
                    mdn_url = p["cmd"].mdn_url
                    encryption_algorithm = p["cmd"].encryption_algorithm
                    signature_algorithm = p["cmd"].signature_algorithm
                    edi_version = p["cmd"].edi_version
                    active = p.get("status", "INACTIVE") == "ACTIVE"

                return FakePartnership()
        return None

    async def create_outbox_event(
        self, tenant_id: int, event_type: str, payload: dict[str, Any]
    ) -> None:
        self.outbox_events.append(
            {"tenant_id": tenant_id, "event_type": event_type, "payload": payload}
        )

    async def update_partner_status(
        self, tenant_id: int, partner_id: uuid.UUID, status: str
    ) -> None:
        for p in self.partners:
            if p["id"] == partner_id and p["tenant_id"] == tenant_id:
                p["status"] = status

    async def list_trading_partners(self) -> list[Any]:
        return self.partners

    async def list_as2_partners(self, tenant_id: int) -> Sequence[Any]:
        return [p for p in self.partners if p["tenant_id"] == tenant_id]

    async def list_partnerships(self) -> list[Any]:
        return self.partnerships

    async def get_as2_partners_by_ids(
        self, ids: list[uuid.UUID], tenant_id: int
    ) -> dict[uuid.UUID, str]:
        return {
            p["id"]: p["cmd"].name
            for p in self.partners
            if p["id"] in ids and p["tenant_id"] == tenant_id
        }


class FakeRoute:
    def __init__(self, id, cmd):
        self.id = id
        self.as2_partner_id = getattr(cmd, "as2_partner_id", None)
        self.sftp_partner_id = getattr(cmd, "sftp_partner_id", None)
        self.webhook_partner_id = getattr(cmd, "webhook_partner_id", None)
        self.isa_sender_id = getattr(cmd, "isa_sender_id", "S1")
        self.isa_receiver_id = getattr(cmd, "isa_receiver_id", "R1")


class FakeDataPlaneRepository(DataPlaneRepositoryPort):
    def __init__(self):
        self.inbound_routes = []
        self.outbound_routes = []
        self.sftp_partners = []
        self.webhook_partners = []

    async def create_inbound_route(self, cmd: CreateInboundRouteCmd) -> uuid.UUID:
        r_id = uuid.uuid4()
        self.inbound_routes.append(FakeRoute(r_id, cmd))
        return r_id

    async def create_outbound_route(self, cmd: CreateOutboundRouteCmd) -> uuid.UUID:
        r_id = uuid.uuid4()
        self.outbound_routes.append(FakeRoute(r_id, cmd))
        return r_id

    async def get_all_routes(self) -> dict[str, list[Any]]:
        return {"inbound": self.inbound_routes, "outbound": self.outbound_routes}

    async def create_sftp_partner(self, cmd: CreateSFTPPartnerCmd) -> uuid.UUID:
        p_id = uuid.uuid4()
        self.sftp_partners.append({"id": p_id, "cmd": cmd})
        return p_id

    async def create_webhook_partner(self, cmd: CreateWebhookPartnerCmd) -> uuid.UUID:
        p_id = uuid.uuid4()
        self.webhook_partners.append({"id": p_id, "cmd": cmd})
        return p_id

    async def list_sftp_partners(self) -> Sequence[Any]:
        return self.sftp_partners

    async def get_sftp_partners_by_ids(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        return {p["id"]: p["cmd"].name for p in self.sftp_partners if p["id"] in ids}

    async def list_webhook_partners(self) -> Sequence[Any]:
        return self.webhook_partners

    async def get_webhook_partners_by_ids(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        return {p["id"]: p["cmd"].name for p in self.webhook_partners if p["id"] in ids}


class FakeTenantRepository(TenantRepositoryPort):
    def __init__(self):
        self.flags = {}

    async def get_tenant_flags(self, tenant_id: int) -> dict[str, Any] | None:
        return self.flags.get(tenant_id)


class MockResult:
    def __init__(self, items):
        self.items = items

    def scalars(self):
        return self

    def all(self):
        return self.items


class MockSession:
    def __init__(self, control_plane):
        self.control_plane = control_plane

    async def execute(self, statement):
        table_name = str(statement)
        if "as2_partnerships" in table_name or "AS2Partnership" in table_name:

            class P:
                def __init__(self):
                    self.id = "123"
                    self.tenant_id = 0
                    self.name = "Test Partnership"
                    self.local_partner_id = "456"
                    self.remote_partner_id = "789"
                    self.mdn_type = "SYNC"
                    self.mdn_url = None
                    self.encryption_algorithm = "AES256"
                    self.signature_algorithm = "SHA256"
                    self.edi_version = None
                    self.active = True

            return MockResult([P()])
        else:

            class T:
                def __init__(self):
                    self.id = "123"
                    self.name = "Test"
                    self.as2_id = "TEST"
                    self.is_local = True
                    self.url = None
                    self.active = True

            return MockResult([T()])


class FakeUnitOfWork:
    def __init__(self):
        self.control_plane = FakeControlPlaneRepository()
        self.data_plane = FakeDataPlaneRepository()
        self.global_session = MockSession(self.control_plane)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass
