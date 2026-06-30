import uuid

import pytest
from api.core.provisioning import ProvisioningService
from api.domain.models import (
    CreateAS2TradingPartnerCmd,
    CreateInboundRouteCmd,
    CreateOutboundRouteCmd,
    CreateSFTPPartnerCmd,
    CreateWebhookPartnerCmd,
)
from api_fakes import FakeControlPlaneRepository, FakeDataPlaneRepository


@pytest.fixture
def service():
    global_repo = FakeControlPlaneRepository()
    tenant_repo = FakeDataPlaneRepository()
    return ProvisioningService(global_repo=global_repo, tenant_repo=tenant_repo)


@pytest.mark.asyncio
async def test_create_as2_partner(service: ProvisioningService):
    cmd = CreateAS2TradingPartnerCmd(name="Test Partner", as2_id="TEST_AS2")
    partner = await service.create_as2_partner(tenant_id=1, cmd=cmd)

    assert partner.type == "AS2"
    assert partner.tenant_id == 1
    assert partner.status == "PROVISIONING"

    global_repo: FakeControlPlaneRepository = service.global_repo
    assert len(global_repo.partners) == 1
    assert len(global_repo.outbox_events) == 1
    assert global_repo.outbox_events[0]["event_type"] == "AS2_PARTNER_CREATED"
    assert global_repo.outbox_events[0]["tenant_id"] == 1


@pytest.mark.asyncio
async def test_create_sftp_partner(service: ProvisioningService):
    cmd = CreateSFTPPartnerCmd(
        name="SFTP Partner",
        host="sftp.example.com",
        username="user",
        credentials_vault_ref="vault-ref",
    )
    partner = await service.create_sftp_partner(tenant_id=1, cmd=cmd)

    assert partner.type == "SFTP"
    assert partner.status == "ACTIVE"

    tenant_repo: FakeDataPlaneRepository = service.tenant_repo
    assert len(tenant_repo.sftp_partners) == 1


@pytest.mark.asyncio
async def test_create_webhook_partner(service: ProvisioningService):
    cmd = CreateWebhookPartnerCmd(
        name="Webhook Partner", url="https://example.com/webhook", auth_header_vault_ref="vault-ref"
    )
    partner = await service.create_webhook_partner(tenant_id=1, cmd=cmd)

    assert partner.type == "WEBHOOK"
    assert partner.status == "ACTIVE"

    tenant_repo: FakeDataPlaneRepository = service.tenant_repo
    assert len(tenant_repo.webhook_partners) == 1


@pytest.mark.asyncio
async def test_list_routes(service: ProvisioningService):
    tenant_repo: FakeDataPlaneRepository = service.tenant_repo
    global_repo: FakeControlPlaneRepository = service.global_repo

    # 1. Create a fake AS2 partner for name resolution
    as2_id = await global_repo.create_as2_identity(
        tenant_id=1, cmd=CreateAS2TradingPartnerCmd(name="Walmart", as2_id="WM")
    )
    sftp_id = await tenant_repo.create_sftp_partner(
        cmd=CreateSFTPPartnerCmd(
            name="Internal SFTP",
            host="sftp.example.com",
            username="user",
            credentials_vault_ref="vault-ref",
        )
    )

    class FakeRoute:
        def __init__(self, id, as2_partner_id, sftp_partner_id, webhook_partner_id):
            self.id = id
            self.as2_partner_id = as2_partner_id
            self.sftp_partner_id = sftp_partner_id
            self.webhook_partner_id = webhook_partner_id
            self.isa_sender_id = "S1"
            self.isa_receiver_id = "R1"
            self.transaction_type = "850"

    # Mocking what the repository would return (objects with properties)
    inbound_route = FakeRoute(uuid.uuid4(), as2_id, sftp_id, None)
    outbound_route = FakeRoute(uuid.uuid4(), as2_id, None, None)

    tenant_repo.inbound_routes = [inbound_route]
    tenant_repo.outbound_routes = [outbound_route]

    routes = await service.list_routes(1)

    assert len(routes) == 2
    inbound_res = next(r for r in routes if r["direction"] == "INBOUND")
    outbound_res = next(r for r in routes if r["direction"] == "OUTBOUND")

    assert inbound_res["destination_name"] == "Walmart"
    assert outbound_res["destination_name"] == "Walmart"


@pytest.mark.asyncio
async def test_create_inbound_route(service: ProvisioningService):
    cmd = CreateInboundRouteCmd(
        isa_sender_id="S1",
        isa_receiver_id="R1",
        transaction_type="850",
        as2_partner_id=uuid.uuid4(),
    )
    route = await service.create_inbound_route(tenant_id=1, cmd=cmd)

    assert route.direction == "INBOUND"
    tenant_repo: FakeDataPlaneRepository = service.tenant_repo
    assert len(tenant_repo.inbound_routes) == 1


@pytest.mark.asyncio
async def test_create_outbound_route(service: ProvisioningService):
    cmd = CreateOutboundRouteCmd(
        isa_sender_id="S1",
        isa_receiver_id="R1",
        transaction_type="855",
        as2_partner_id=uuid.uuid4(),
    )
    route = await service.create_outbound_route(tenant_id=1, cmd=cmd)

    assert route.direction == "OUTBOUND"
    tenant_repo: FakeDataPlaneRepository = service.tenant_repo
    assert len(tenant_repo.outbound_routes) == 1
