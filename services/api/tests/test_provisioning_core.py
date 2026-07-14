import uuid

import pytest
from api.core.services import (
    AS2PartnerService,
    AS2PartnershipService,
    RouteService,
    SFTPPartnerService,
    WebhookService,
)
from api.domain.models import (
    CreateAS2TradingPartnerCmd,
    CreateInboundRouteCmd,
    CreateOutboundRouteCmd,
    CreateSFTPPartnerCmd,
    CreateWebhookCmd,
    UpdateAS2TradingPartnerCmd,
)
from api_fakes import FakeControlPlaneRepository


@pytest.fixture
def global_repo():
    return FakeControlPlaneRepository()


@pytest.fixture
def as2_partner_service(global_repo):
    return AS2PartnerService(global_repo=global_repo)


@pytest.fixture
def as2_partnership_service(global_repo):
    return AS2PartnershipService(global_repo=global_repo)


@pytest.fixture
def sftp_partner_service(global_repo):
    return SFTPPartnerService(global_repo=global_repo)


@pytest.fixture
def webhook_service(global_repo):
    return WebhookService(global_repo=global_repo)


@pytest.fixture
def route_service(global_repo):
    return RouteService(global_repo=global_repo)


@pytest.mark.asyncio
async def test_create_as2_partner(as2_partner_service: AS2PartnerService, global_repo):
    cmd = CreateAS2TradingPartnerCmd(name="Test Partner", as2_id="TEST_AS2")
    partner = await as2_partner_service.create_as2_partner(tenant_id=1, cmd=cmd)

    assert partner.type == "AS2"
    assert partner.tenant_id == 1
    assert partner.status == "PROVISIONING"

    assert len(global_repo.partners) == 1
    assert len(global_repo.outbox_events) == 1
    assert global_repo.outbox_events[0]["event_type"] == "AS2_PARTNER_CREATED"
    assert global_repo.outbox_events[0]["tenant_id"] == 1


@pytest.mark.asyncio
async def test_update_and_delete_as2_partner(as2_partner_service: AS2PartnerService, global_repo):
    cmd = CreateAS2TradingPartnerCmd(name="Test Partner", as2_id="TEST_AS2")
    partner = await as2_partner_service.create_as2_partner(tenant_id=1, cmd=cmd)

    # Update
    update_cmd = UpdateAS2TradingPartnerCmd(name="Updated Partner", as2_id="NEW_AS2")
    updated = await as2_partner_service.update_as2_partner(
        tenant_id=1, partner_id=partner.partner_id, cmd=update_cmd
    )
    assert updated.name == "Updated Partner"

    # Delete
    await as2_partner_service.delete_as2_partner(tenant_id=1, partner_id=partner.partner_id)
    assert len(global_repo.partners) == 0


@pytest.mark.asyncio
async def test_create_sftp_partner(sftp_partner_service: SFTPPartnerService, global_repo):
    cmd = CreateSFTPPartnerCmd(
        name="SFTP Partner",
        host="sftp.example.com",
        username="user",
        credentials_vault_ref="vault-ref",
    )
    partner = await sftp_partner_service.create_sftp_partner(tenant_id=1, cmd=cmd)

    assert partner.type == "SFTP"
    assert partner.status == "INACTIVE"
    assert len(global_repo.sftp_partners) == 1


@pytest.mark.asyncio
async def test_create_webhook(webhook_service: WebhookService, global_repo):
    cmd = CreateWebhookCmd(
        name="Webhook Partner", url="https://example.com/webhook", auth_header_vault_ref="vault-ref"
    )
    partner = await webhook_service.create_webhook(tenant_id=1, cmd=cmd)

    assert partner.type == "WEBHOOK"
    assert partner.status == "ACTIVE"
    assert len(global_repo.webhooks) == 1


@pytest.mark.asyncio
async def test_list_routes(route_service: RouteService, global_repo):
    as2_id = await global_repo.create_as2_identity(
        tenant_id=1, cmd=CreateAS2TradingPartnerCmd(name="Walmart", as2_id="WM")
    )
    sftp_id = await global_repo.create_sftp_partner(
        tenant_id=1,
        cmd=CreateSFTPPartnerCmd(
            name="Internal SFTP",
            host="sftp.example.com",
            username="user",
            credentials_vault_ref="vault-ref",
        ),
    )

    class FakeRoute:
        def __init__(self, id, as2_partner_id, sftp_partner_id, webhook_id):
            self.id = id
            self.name = "Test Route"
            self.processing_mode = "TRANSLATE"
            self.active = True
            self.as2_partner_id = as2_partner_id
            self.sftp_partner_id = sftp_partner_id
            self.webhook_id = webhook_id
            self.isa_sender_id = "S1"
            self.isa_receiver_id = "R1"
            self.gs_sender_id = "S1"
            self.gs_receiver_id = "R1"
            self.transaction_type = "850"
            self.trading_partner_id = uuid.uuid4()
            self.isa_sender_qualifier = "ZZ"
            self.isa_receiver_qualifier = "ZZ"
            self.default_standard = "x12"
            self.default_version = "004010"

    global_repo.inbound_routes = [FakeRoute(uuid.uuid4(), as2_id, sftp_id, None)]
    global_repo.outbound_routes = [FakeRoute(uuid.uuid4(), as2_id, None, None)]

    routes = await route_service.list_routes(1)

    assert len(routes) == 2
    inbound_res = next(r for r in routes if r["direction"] == "INBOUND")
    outbound_res = next(r for r in routes if r["direction"] == "OUTBOUND")

    assert inbound_res["destination_name"] == "Walmart"
    assert outbound_res["destination_name"] == "Walmart"


@pytest.mark.asyncio
async def test_create_inbound_route(route_service: RouteService, global_repo):
    cmd = CreateInboundRouteCmd(
        name="Inbound Route",
        isa_sender_id="S1",
        isa_receiver_id="R1",
        transaction_type="850",
        as2_partner_id=uuid.uuid4(),
    )
    route = await route_service.create_inbound_route(tenant_id=1, cmd=cmd)

    assert route.direction == "INBOUND"
    assert len(global_repo.inbound_routes) == 1


@pytest.mark.asyncio
async def test_create_outbound_route(route_service: RouteService, global_repo):
    cmd = CreateOutboundRouteCmd(
        trading_partner_id=str(uuid.uuid4()),
        name="Outbound Route",
        as2_partner_id=uuid.uuid4(),
    )
    route = await route_service.create_outbound_route(tenant_id=1, cmd=cmd)

    assert route.direction == "OUTBOUND"
    assert len(global_repo.outbound_routes) == 1
