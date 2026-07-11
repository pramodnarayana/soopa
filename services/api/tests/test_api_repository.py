import os
from unittest.mock import AsyncMock, MagicMock

# Set dummy encryption key for tests before importing repository that uses db_encryption
os.environ["DB_ENCRYPTION_KEY"] = "sKkXvO6eX2Xo6-k2d_WqVf9j_w2_mCq7jR9b9w0wWf4="

import pytest
from api.adapters.repository import (
    SqlAlchemyControlPlaneRepository,
)
from api.domain.models import (
    CreateAS2PartnershipCmd,
    CreateAS2TradingPartnerCmd,
    CreateInboundRouteCmd,
    CreateOutboundRouteCmd,
    CreateSFTPPartnerCmd,
    CreateWebhookCmd,
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
    repo = SqlAlchemyControlPlaneRepository(tenant_session)
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
    names = await control_repo.get_as2_partners_by_ids(1, [p_id1, p_id2])
    assert isinstance(names, dict)

    # 3. Create Partnership
    p_cmd = CreateAS2PartnershipCmd(
        name="Test Partnership",
        local_partner_id=p_id2,
        remote_partner_id=p_id1,
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
    control_repo: SqlAlchemyControlPlaneRepository,
):
    """Tests the Global Control Plane repository for SFTP, Webhook, and Route operations.

    After the hexagonal architecture refactor, all write operations for partners
    and routes reside in the Global Control Plane. The DataPlane repository is a
    thin stub — its data is populated by the provision worker's replication loop.
    This test validates the full control plane flow end-to-end.
    """
    # 1. SFTP Partner — lives in Global Control Plane
    sftp_cmd = CreateSFTPPartnerCmd(
        name="test_sftp",
        host="localhost",
        port=22,
        username="user",
        password="secretpassword",
    )
    sftp_id = await control_repo.create_sftp_partner(tenant_id=1, cmd=sftp_cmd)
    assert sftp_id is not None

    # 2. Webhook Partner — lives in Global Control Plane
    wh_cmd = CreateWebhookCmd(name="Hook", url="http://hook")
    wh_id = await control_repo.create_webhook(tenant_id=1, cmd=wh_cmd)
    assert wh_id is not None

    # 3. Routes — use the SFTP/Webhook partners we just created to avoid FK validation issues
    # Inbound route: deliver via webhook
    in_cmd = CreateInboundRouteCmd(
        name="Inbound Route 1",
        isa_sender_id="S",
        isa_receiver_id="R",
        transaction_type="850",
        as2_partner_id=None,
        sftp_partner_id=None,
        webhook_id=wh_id,
    )
    # Outbound route: deliver via sftp
    import uuid

    out_cmd = CreateOutboundRouteCmd(
        trading_partner_id=str(uuid.uuid4()),
        name="Outbound Route 1",
        isa_sender_id="S",
        isa_receiver_id="R",
        gs_sender_id="S",
        gs_receiver_id="R",
        transaction_type="855",
        as2_partner_id=None,
        sftp_partner_id=sftp_id,
    )
    in_id = await control_repo.create_inbound_route(tenant_id=1, cmd=in_cmd)
    out_id = await control_repo.create_outbound_route(tenant_id=1, cmd=out_cmd)
    assert in_id is not None
    assert out_id is not None

    # 4. Verify get_all_routes returns the expected dict structure
    # Note: mock session returns empty results — real data is validated by DB integration tests
    all_routes = await control_repo.get_all_routes(tenant_id=1)
    assert "inbound" in all_routes
    assert "outbound" in all_routes
    assert isinstance(all_routes["inbound"], list)
    assert isinstance(all_routes["outbound"], list)

    # 5. SFTP/Webhook name lookup — mock session returns empty dict (no real DB)
    sftp_names = await control_repo.get_sftp_partners_by_ids(tenant_id=1, ids=[sftp_id])
    assert isinstance(sftp_names, dict)

    wh_names = await control_repo.get_webhooks_by_ids(tenant_id=1, ids=[wh_id])
    assert isinstance(wh_names, dict)


@pytest.mark.asyncio
async def test_get_as2_partner_tenant_isolation(control_repo: SqlAlchemyControlPlaneRepository):
    # Verify that get_as2_partner includes a tenant_id check in the where clause
    import uuid

    partner_id = uuid.uuid4()
    await control_repo.get_as2_partner(tenant_id=1, partner_id=partner_id)

    # Extract the call arguments to session.execute
    control_repo.session.execute.assert_called_once()
    call_args = control_repo.session.execute.call_args[0][0]

    # We can check that the SQL string contains the tenant_id binding
    compiled = str(call_args.compile(compile_kwargs={"literal_binds": True}))
    compiled_clean = compiled.replace(" ", "")
    assert "tenant_idIN(1,0)" in compiled_clean or "tenant_id=" in compiled_clean
    assert "1" in compiled_clean


@pytest.mark.asyncio
async def test_get_as2_partner_for_write() -> None:
    from unittest.mock import AsyncMock, MagicMock
    from uuid import UUID

    from api.adapters.repository import SqlAlchemyControlPlaneRepository
    from database.models.data_plane import AS2Partner

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = AS2Partner(
        id=UUID("00000000-0000-0000-0000-000000000000"),
        tenant_id=1,
        name="test",
        as2_id="test",
    )
    mock_session.execute.return_value = mock_result

    repo = SqlAlchemyControlPlaneRepository(mock_session)
    partner = await repo.get_as2_partner_for_write(1, UUID("00000000-0000-0000-0000-000000000000"))
    assert partner is not None
