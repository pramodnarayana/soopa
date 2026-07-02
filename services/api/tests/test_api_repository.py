from unittest.mock import AsyncMock, MagicMock

import pytest
from api.adapters.repository import SqlAlchemyControlPlaneRepository, SqlAlchemyDataPlaneRepository
from api.domain.models import (
    CreateAS2PartnershipCmd,
    CreateAS2TradingPartnerCmd,
    CreateInboundRouteCmd,
    CreateOutboundRouteCmd,
    CreateSFTPPartnerCmd,
    CreateWebhookPartnerCmd,
)


@pytest.fixture
def global_session():
    session = AsyncMock()
    # For execute().scalars().all() -> [...]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute.return_value = mock_result
    # session.add is a sync method
    session.add = MagicMock()
    return session


@pytest.fixture
def tenant_session():
    session = AsyncMock()
    # For execute().scalars().all() -> [...]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute.return_value = mock_result
    # session.add is a sync method
    session.add = MagicMock()
    return session


@pytest.fixture
def control_repo(global_session):
    return SqlAlchemyControlPlaneRepository(global_session)


@pytest.fixture
def tenant_repo(tenant_session):
    repo = SqlAlchemyDataPlaneRepository(tenant_session)
    repo._tenant_id = MagicMock(return_value=1)
    return repo


@pytest.mark.asyncio
@pytest.mark.integration
async def test_control_plane_repository(control_repo: SqlAlchemyControlPlaneRepository):
    # 1. Create Identity
    cmd1 = CreateAS2TradingPartnerCmd(name="Test Partner", as2_id="TEST_AS2", is_local=False)
    p_id1 = await control_repo.create_as2_identity(tenant_id=1, cmd=cmd1)

    cmd2 = CreateAS2TradingPartnerCmd(name="Test Partner 2", as2_id="TEST_AS2_2", is_local=True)
    p_id2 = await control_repo.create_as2_identity(tenant_id=1, cmd=cmd2)

    assert p_id1 is not None
    assert p_id2 is not None

    # 2. Get Partners by IDs
    names = await control_repo.get_as2_partners_by_ids([p_id1, p_id2], 1)
    assert names == {}

    # 3. Create Partnership
    p_cmd = CreateAS2PartnershipCmd(
        name="Test Partnership", local_partner_id=p_id2, remote_partner_id=p_id1
    )
    partnership_id = await control_repo.create_as2_partnership(tenant_id=1, cmd=p_cmd)

    assert partnership_id is not None

    # 4. Outbox Event
    event_id = await control_repo.create_outbox_event(
        tenant_id=1, event_type="TEST_EVENT", payload={"key": "value"}
    )
    assert event_id is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_data_plane_repository(
    tenant_repo: SqlAlchemyDataPlaneRepository, control_repo: SqlAlchemyControlPlaneRepository
):
    # Since DataPlane relies on AS2 partners created in ControlPlane (foreign keys usually but in our setup it's loosely coupled or tenant DB)
    import uuid

    as2_id = uuid.uuid4()

    # 1. SFTP Partner
    sftp_cmd = CreateSFTPPartnerCmd(
        name="SFTP", host="sftp.example.com", username="user", credentials_vault_ref="ref"
    )
    sftp_id = await tenant_repo.create_sftp_partner(sftp_cmd)

    # 2. Webhook Partner
    wh_cmd = CreateWebhookPartnerCmd(name="Hook", url="http://hook")
    wh_id = await tenant_repo.create_webhook_partner(wh_cmd)

    # 3. Routes
    in_cmd = CreateInboundRouteCmd(
        isa_sender_id="S",
        isa_receiver_id="R",
        transaction_type="850",
        as2_partner_id=as2_id,
        webhook_partner_id=None,
    )
    out_cmd = CreateOutboundRouteCmd(
        isa_sender_id="S",
        isa_receiver_id="R",
        transaction_type="855",
        as2_partner_id=as2_id,
        sftp_partner_id=None,
    )

    in_id = await tenant_repo.create_inbound_route(in_cmd)
    out_id = await tenant_repo.create_outbound_route(out_cmd)

    assert in_id is not None
    assert out_id is not None

    # 4. Get all routes
    all_routes = await tenant_repo.get_all_routes()
    assert all_routes["inbound"] == []
    assert all_routes["outbound"] == []

    # 5. Get by IDs
    sftp_names = await tenant_repo.get_sftp_partners_by_ids([sftp_id])
    assert sftp_names == {}

    wh_names = await tenant_repo.get_webhook_partners_by_ids([wh_id])
    assert wh_names == {}
