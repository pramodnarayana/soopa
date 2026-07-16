import uuid
from collections.abc import Sequence
from typing import Any

from api.domain.models import (
    CreateAS2PartnershipCmd,
    CreateAS2TradingPartnerCmd,
    CreateInboundRouteCmd,
    CreateOutboundRouteCmd,
    CreateSFTPPartnerCmd,
    CreateWebhookCmd,
    UpdateAS2PartnershipCmd,
    UpdateAS2TradingPartnerCmd,
    UpdateInboundRouteCmd,
    UpdateOutboundRouteCmd,
    UpdateSFTPPartnerCmd,
)
from api.ports.repository import (
    TenantRepositoryPort,
)


class FakeGlobalStore:
    def __init__(self):
        self.partners = []
        self.partnerships = []
        self.sftp_partners = []
        self.webhooks = []
        self.outbox_events = []

    async def create_as2_identity(
        self, tenant_id: int, cmd: CreateAS2TradingPartnerCmd
    ) -> uuid.UUID:
        for p in self.partners:
            if p["tenant_id"] == tenant_id and p["cmd"].as2_id == cmd.as2_id:
                from sqlalchemy.exc import IntegrityError

                raise IntegrityError("mock error", params={}, orig=Exception("mock"))
        p_id = uuid.uuid4()
        self.partners.append({"id": p_id, "tenant_id": tenant_id, "cmd": cmd})
        return p_id

    async def update_as2_identity(
        self, tenant_id: int, partner_id: uuid.UUID, cmd: UpdateAS2TradingPartnerCmd
    ) -> None:
        for p in self.partners:
            if p["id"] == partner_id and p["tenant_id"] == tenant_id:
                p["updated_name"] = getattr(cmd, "name", p["cmd"].name)
                break

    async def delete_as2_identity(self, tenant_id: int, partner_id: uuid.UUID) -> None:
        self.partners = [
            p for p in self.partners if not (p["id"] == partner_id and p["tenant_id"] == tenant_id)
        ]

    async def create_sftp_partner(self, tenant_id: int, cmd: CreateSFTPPartnerCmd) -> uuid.UUID:
        p_id = uuid.uuid4()
        self.sftp_partners.append({"id": p_id, "tenant_id": tenant_id, "cmd": cmd})
        return p_id

    async def update_sftp_partner(
        self, tenant_id: int, partner_id: uuid.UUID, cmd: UpdateSFTPPartnerCmd
    ) -> bool:
        return True

    async def delete_sftp_partner(self, tenant_id: int, partner_id: uuid.UUID) -> None:
        self.sftp_partners = [
            p
            for p in self.sftp_partners
            if not (p["id"] == partner_id and p["tenant_id"] == tenant_id)
        ]

    async def create_as2_partnership(
        self, tenant_id: int, cmd: CreateAS2PartnershipCmd
    ) -> uuid.UUID:
        p_id = uuid.uuid4()
        self.partnerships.append({"id": p_id, "tenant_id": tenant_id, "cmd": cmd})
        return p_id

    async def update_as2_partnership(
        self, tenant_id: int, partnership_id: uuid.UUID, cmd: UpdateAS2PartnershipCmd
    ) -> None:
        pass

    async def delete_as2_partnership(self, tenant_id: int, partnership_id: uuid.UUID) -> None:
        self.partnerships = [
            p
            for p in self.partnerships
            if not (p["id"] == partnership_id and p["tenant_id"] == tenant_id)
        ]

    async def get_as2_partner(self, tenant_id: int, partner_id: uuid.UUID) -> Any:
        for p in self.partners:
            if p["id"] == partner_id and p["tenant_id"] == tenant_id:
                # Mock an AS2Partner DB object
                class FakePartner:
                    id = p["id"]
                    tenant_id = p["tenant_id"]
                    name = p.get("updated_name", p["cmd"].name)
                    as2_id = p["cmd"].as2_id
                    is_local = p["cmd"].is_local
                    url = p["cmd"].url
                    active = p.get("status", "INACTIVE") == "ACTIVE"
                    private_key_vault_ref = None
                    prev_private_key_vault_ref = None
                    public_cert_pem = p["cmd"].public_cert_pem
                    public_cert_vault_ref = p["cmd"].public_cert_vault_ref
                    prev_public_cert_pem = None

                return FakePartner()
        return None

    async def get_as2_partnership(self, tenant_id: int, partnership_id: uuid.UUID) -> Any:
        for p in self.partnerships:
            if p["id"] == partnership_id and p["tenant_id"] == tenant_id:

                class FakePartnership:
                    id = p["id"]
                    tenant_id = p["tenant_id"]
                    name = p["cmd"].name
                    trading_partner_id = getattr(p["cmd"], "trading_partner_id", None)
                    local_partner_id = p["cmd"].local_partner_id
                    remote_partner_id = p["cmd"].remote_partner_id
                    mdn_type = p["cmd"].mdn_type
                    mdn_url = p["cmd"].mdn_url
                    encryption_algorithm = p["cmd"].encryption_algorithm
                    signature_algorithm = p["cmd"].signature_algorithm

                    active = p.get("status", "INACTIVE") == "ACTIVE"
                    private_key_vault_ref = None
                    prev_private_key_vault_ref = None
                    public_cert_pem = None
                    prev_public_cert_pem = None

                return FakePartnership()
        return None

    async def publish_outbox_event(
        self,
        tenant_id: int,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: uuid.UUID | None = None,
    ) -> uuid.UUID:
        key = idempotency_key or uuid.uuid4()
        self.outbox_events.append(
            {
                "tenant_id": tenant_id,
                "event_type": event_type,
                "payload": payload,
                "idempotency_key": key,
            }
        )
        return key

    async def update_partner_status(
        self, tenant_id: int, partner_id: uuid.UUID, status: str
    ) -> None:
        for p in self.partners:
            if p["id"] == partner_id and p["tenant_id"] == tenant_id:
                p["status"] = status

    async def list_trading_partners(self) -> list[Any]:
        return self.partners

    async def list_as2_partners(self, tenant_id: int) -> Sequence[Any]:
        results = []
        for p in self.partners:
            if p["tenant_id"] == tenant_id:

                class FakePartner:
                    id = p["id"]
                    tenant_id = p["tenant_id"]
                    name = p["cmd"].name
                    as2_id = p["cmd"].as2_id
                    is_local = p["cmd"].is_local
                    url = p["cmd"].url
                    active = p.get("status", "INACTIVE") == "ACTIVE"

                results.append(FakePartner())
        return results

    async def list_partnerships(self) -> list[Any]:
        return self.partnerships

    async def get_as2_partners_by_ids(
        self, tenant_id: int, ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        return {
            p["id"]: p["cmd"].name
            for p in self.partners
            if p["id"] in ids and p["tenant_id"] == tenant_id
        }

    async def get_sftp_partners_by_ids(
        self, tenant_id: int, ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        return {
            p["id"]: p["cmd"].name
            for p in self.sftp_partners
            if p["id"] in ids and p["tenant_id"] == tenant_id
        }

    async def create_webhook(self, tenant_id: int, cmd: CreateWebhookCmd) -> uuid.UUID:
        wh_id = uuid.uuid4()
        self.webhooks.append({"id": wh_id, "tenant_id": tenant_id, "cmd": cmd})
        return wh_id

    async def update_webhook(
        self,
        tenant_id: int,
        webhook_id: uuid.UUID,
        name: str | None = None,
        active: bool | None = None,
        url: str | None = None,
    ) -> bool:
        return True

    async def delete_webhook(self, tenant_id: int, webhook_id: uuid.UUID) -> bool:
        self.webhooks = [
            w for w in self.webhooks if not (w["id"] == webhook_id and w["tenant_id"] == tenant_id)
        ]
        return True

    async def get_webhooks_by_ids(
        self, tenant_id: int, ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        return {
            p["id"]: p["cmd"].name
            for p in self.webhooks
            if p["id"] in ids and p["tenant_id"] == tenant_id
        }

    async def create_inbound_route(self, tenant_id: int, cmd: CreateInboundRouteCmd) -> uuid.UUID:
        r_id = uuid.uuid4()
        if not hasattr(self, "inbound_routes"):
            self.inbound_routes = []
        self.inbound_routes.append(FakeRoute(r_id, cmd))
        return r_id

    async def create_outbound_route(self, tenant_id: int, cmd: CreateOutboundRouteCmd) -> uuid.UUID:
        r_id = uuid.uuid4()
        if not hasattr(self, "outbound_routes"):
            self.outbound_routes = []
        self.outbound_routes.append(FakeRoute(r_id, cmd))
        return r_id

    async def update_inbound_route(
        self, tenant_id: int, route_id: uuid.UUID, cmd: UpdateInboundRouteCmd
    ) -> bool:
        return True

    async def delete_inbound_route(self, tenant_id: int, route_id: uuid.UUID) -> bool:
        return True

    async def update_outbound_route(
        self, tenant_id: int, route_id: uuid.UUID, cmd: UpdateOutboundRouteCmd
    ) -> bool:
        return True

    async def delete_outbound_route(self, tenant_id: int, route_id: uuid.UUID) -> bool:
        return True

    async def list_inbound_routes(self, tenant_id: int) -> list[Any]:
        return getattr(self, "inbound_routes", [])

    async def list_outbound_routes(self, tenant_id: int) -> list[Any]:
        return getattr(self, "outbound_routes", [])

    async def list_sftp_partners(self, tenant_id: int) -> Sequence[Any]:
        return [p for p in getattr(self, "sftp_partners", []) if p["tenant_id"] == tenant_id]

    async def list_webhooks(self, tenant_id: int) -> Sequence[Any]:
        return [p for p in getattr(self, "webhooks", []) if p["tenant_id"] == tenant_id]

    async def get_sftp_partner(self, tenant_id: int, partner_id: uuid.UUID) -> Any:
        for p in self.sftp_partners:
            if p["id"] == partner_id and p["tenant_id"] == tenant_id:

                class MockPartner:
                    id = p["id"]
                    tenant_id = p["tenant_id"]
                    name = p["cmd"].name
                    active = True
                    host = p["cmd"].host
                    port = p["cmd"].port
                    username = p["cmd"].username
                    inbound_remote_path = getattr(p["cmd"], "inbound_remote_path", None)
                    outbound_remote_path = getattr(p["cmd"], "outbound_remote_path", None)
                    host_key = getattr(p["cmd"], "host_key", None)
                    password_encrypted = b"encrypted"
                    credentials_vault_ref = None

                return MockPartner()
        return None

    async def get_webhook(self, tenant_id: int, partner_id: uuid.UUID) -> Any:
        for p in self.webhooks:
            if p["id"] == partner_id and p["tenant_id"] == tenant_id:

                class MockWebhook:
                    id = p["id"]
                    tenant_id = p["tenant_id"]
                    name = p["cmd"].name
                    active = True
                    url = getattr(p["cmd"], "url", None)

                return MockWebhook()
        return None


class FakeRoute:
    def __init__(self, id, cmd):
        self.id = id
        self.name = getattr(cmd, "name", "Test Route")
        self.processing_mode = getattr(cmd, "processing_mode", "TRANSFORM")
        self.active = True
        self.as2_partner_id = getattr(cmd, "as2_partner_id", None)
        self.sftp_partner_id = getattr(cmd, "sftp_partner_id", None)
        self.webhook_id = getattr(cmd, "webhook_id", None)
        self.isa_sender_id = getattr(cmd, "isa_sender_id", "S1")
        self.isa_receiver_id = getattr(cmd, "isa_receiver_id", "R1")


class FakeTenantStore:
    def __init__(self):
        self.inbound_routes = []
        self.outbound_routes = []
        self.sftp_partners = []
        self.webhooks = []

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

    async def get_sftp_partner(self, partner_id: uuid.UUID) -> Any:
        for p in self.sftp_partners:
            if p["id"] == partner_id:

                class MockPartner:
                    id = p["id"]
                    tenant_id = 1
                    name = p["cmd"].name
                    active = True
                    host = p["cmd"].host
                    port = p["cmd"].port
                    username = p["cmd"].username
                    inbound_remote_path = getattr(p["cmd"], "inbound_remote_path", None)
                    outbound_remote_path = getattr(p["cmd"], "outbound_remote_path", None)
                    host_key = getattr(p["cmd"], "host_key", None)

                return MockPartner()
        return None

    async def create_webhook(self, cmd: CreateWebhookCmd) -> uuid.UUID:
        p_id = uuid.uuid4()
        self.webhooks.append({"id": p_id, "cmd": cmd})
        return p_id

    async def get_webhook(self, partner_id: uuid.UUID) -> Any:
        for p in self.webhooks:
            if p["id"] == partner_id:

                class MockWebhook:
                    id = p["id"]
                    tenant_id = 1
                    name = p["cmd"].name
                    active = True
                    url = getattr(p["cmd"], "url", None)

                return MockWebhook()
        return None

    async def list_sftp_partners(self) -> Sequence[Any]:
        return self.sftp_partners

    async def get_sftp_partners_by_ids(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        return {p["id"]: p["cmd"].name for p in self.sftp_partners if p["id"] in ids}

    async def list_webhooks(self) -> Sequence[Any]:
        return self.webhooks

    async def get_webhooks_by_ids(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        return {p["id"]: p["cmd"].name for p in self.webhooks if p["id"] in ids}


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
    def __init__(self, global_store):
        self.global_store = global_store

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
        repo = FakeGlobalStore()
        self.api_tokens = repo
        self.as2_partners = repo
        self.as2_partnerships = repo
        self.inbound_routes = repo
        self.outbound_routes = repo
        self.outbox = repo
        self.sftp_partners = repo
        self.tenants = repo
        self.webhooks = repo
        self.edi_headers = repo

        self.transactions = FakeTenantStore()

        self.global_session = MockSession(repo)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass
