import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from api.dependencies.auth import get_current_tenant_id, get_current_user_profile
from api.dependencies.database import get_tenant_uow
from api.domain.models import TransactionDetailDTO
from api.main import app
from fastapi.testclient import TestClient


def override_get_current_user_profile():
    return {"sub": "test-user", "tenant_id": 1}


def override_get_current_tenant_id():
    return 1


def _make_mock_msg() -> MagicMock:
    m = MagicMock()
    m.id = uuid.uuid4()
    m.trace_id = uuid.uuid4()
    m.direction = "INBOUND"
    m.connection_type = "UNKNOWN"
    m.sender_id = "A"
    m.receiver_id = "B"
    m.gs_sender_id = "A"
    m.gs_receiver_id = "B"
    m.status = "SUCCESS"
    m.edi_data = "TEST"
    m.created_at = datetime.now(UTC)
    m.trading_partner_id = "TEST_PARTNER_01"
    return m


def _make_mock_json() -> MagicMock:
    j = MagicMock()
    j.id = uuid.uuid4()
    j.transaction_type = "850"
    j.sender_id = "A"
    j.receiver_id = "B"
    j.gs_sender_id = "A"
    j.gs_receiver_id = "B"
    j.business_metadata = {"_routing": {"trading_partner_id": str(uuid.uuid4())}}
    j.payload = "{}"
    j.status = "SUCCESS"
    j.created_at = datetime.now(UTC)
    return j


def _make_mock_gw() -> MagicMock:
    gw = MagicMock()
    gw.id = uuid.uuid4()
    gw.webhook_url = "http://test"
    gw.http_status_code = 200
    gw.payload = "{}"
    gw.response = "{}"
    gw.status = "SUCCESS"
    gw.created_at = datetime.now(UTC)
    return gw


@pytest.fixture
def base_mock_uow():
    """Fresh mock UoW for every test — prevents side_effect state leakage."""
    from api.core.uow import UnitOfWork

    mock_msg = _make_mock_msg()
    mock_json = _make_mock_json()
    mock_gw = _make_mock_gw()

    mock_repo = AsyncMock()
    mock_repo.list_transactions.return_value = [mock_msg]
    from api.domain.models import TransactionDetailDTO

    mock_repo.get_transaction.return_value = TransactionDetailDTO(
        edi_message=mock_msg,
        edi_jsons=[mock_json],
        api_gateways=[mock_gw],
    )
    mock_repo.get_transaction_thread.return_value = [mock_json]

    mock_route = MagicMock()
    mock_route.as2_partner_id = uuid.uuid4()
    mock_route.sftp_partner_id = None

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.side_effect = [mock_route, "Test Partner"]

    mock_scalars = MagicMock()
    mock_scalars.first.side_effect = [mock_route, "Test Partner"]
    mock_db_result.scalars.return_value = mock_scalars

    mock_tenant = AsyncMock()
    mock_tenant.execute.return_value = mock_db_result
    mock_global = AsyncMock()
    mock_global.execute.return_value = mock_db_result

    uow = UnitOfWork(global_session=mock_global, tenant_session=mock_tenant)
    uow._transactions = mock_repo
    return uow


@pytest.fixture(autouse=True)
def setup_dependencies(base_mock_uow):
    app.dependency_overrides[get_current_user_profile] = override_get_current_user_profile
    app.dependency_overrides[get_current_tenant_id] = override_get_current_tenant_id
    app.dependency_overrides[get_tenant_uow] = lambda: base_mock_uow
    yield
    app.dependency_overrides.clear()


client = TestClient(app)


def test_list_transactions():
    response = client.get("/api/v1/transactions")
    assert response.status_code == 200


def test_get_transaction_detail():
    uid = str(uuid.uuid4())
    response = client.get(f"/api/v1/transactions/{uid}")
    assert response.status_code == 200


def test_get_transaction_thread():
    response = client.get("/api/v1/transactions/thread?key=isa_control_number&value=123")
    assert response.status_code == 200


def test_get_transaction_detail_sftp():
    from api.core.uow import UnitOfWork
    from api.dependencies.database import get_tenant_uow

    mock_msg = MagicMock()
    mock_msg.id = uuid.uuid4()
    mock_msg.trace_id = uuid.uuid4()
    mock_msg.trading_partner_id = "TEST_PARTNER_01"
    mock_msg.created_at = None

    mock_repo = AsyncMock()
    mock_repo.get_transaction.return_value = TransactionDetailDTO(
        edi_message=mock_msg,
        edi_jsons=[],
        api_gateways=[],
    )

    mock_route = MagicMock()
    mock_route.as2_partner_id = None
    mock_route.sftp_partner_id = uuid.uuid4()

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.side_effect = [mock_route, "SFTP Partner"]
    mock_scalars = MagicMock()
    mock_scalars.first.side_effect = [mock_route, "SFTP Partner"]
    mock_db_result.scalars.return_value = mock_scalars

    mock_tenant = AsyncMock()
    mock_tenant.execute.return_value = mock_db_result
    mock_global = AsyncMock()
    mock_global.execute.return_value = mock_db_result

    mock_uow = UnitOfWork(global_session=mock_global, tenant_session=mock_tenant)
    mock_uow._transactions = mock_repo

    app.dependency_overrides[get_tenant_uow] = lambda: mock_uow
    response = client.get(f"/api/v1/transactions/{mock_msg.trace_id}")
    assert response.status_code == 200
    assert response.json()["trading_partner_name"] == "SFTP Partner"


def test_get_transaction_detail_fallback():
    from api.core.uow import UnitOfWork
    from api.dependencies.database import get_tenant_uow

    mock_msg = MagicMock()
    mock_msg.id = uuid.uuid4()
    mock_msg.trace_id = uuid.uuid4()
    mock_msg.trading_partner_id = None
    mock_msg.created_at = None

    mock_json = MagicMock()
    mock_json.id = uuid.uuid4()
    mock_json.created_at = None
    mock_json.business_metadata = {"_routing": {"trading_partner_id": str(uuid.uuid4())}}

    mock_repo = AsyncMock()
    mock_repo.get_transaction.return_value = TransactionDetailDTO(
        edi_message=mock_msg,
        edi_jsons=[mock_json],
        api_gateways=[],
    )

    mock_db_result = MagicMock()
    # first call returns None (AS2Partner lookup misses), second returns "Fallback Partner" (SFTPPartner lookup hits)
    mock_db_result.scalar_one_or_none.side_effect = [None, "Fallback Partner"]
    mock_scalars = MagicMock()
    mock_scalars.first.side_effect = [None, "Fallback Partner"]
    mock_db_result.scalars.return_value = mock_scalars

    mock_tenant = AsyncMock()
    mock_tenant.execute.return_value = mock_db_result
    mock_global = AsyncMock()
    mock_global.execute.return_value = mock_db_result

    mock_uow = UnitOfWork(global_session=mock_global, tenant_session=mock_tenant)
    mock_uow._transactions = mock_repo

    app.dependency_overrides[get_tenant_uow] = lambda: mock_uow
    response = client.get(f"/api/v1/transactions/{mock_msg.trace_id}")
    assert response.status_code == 200
    assert response.json()["trading_partner_name"] == "Fallback Partner"


def test_get_transaction_not_found():
    from api.core.uow import UnitOfWork
    from api.dependencies.database import get_tenant_uow

    mock_uow = UnitOfWork(global_session=AsyncMock(), tenant_session=AsyncMock())

    mock_repo = AsyncMock()
    mock_repo.get_transaction.return_value = None
    mock_uow._transactions = mock_repo

    app.dependency_overrides[get_tenant_uow] = lambda: mock_uow
    uid = str(uuid.uuid4())
    response = client.get(f"/api/v1/transactions/{uid}")
    assert response.status_code == 404


def test_get_transaction_webhook_fallback():
    from api.core.uow import UnitOfWork
    from api.dependencies.database import get_tenant_uow

    mock_repo = AsyncMock()

    mock_msg = MagicMock()
    mock_msg.id = uuid.uuid4()
    mock_msg.trace_id = uuid.uuid4()
    mock_msg.direction = "INBOUND"
    mock_msg.sender_id = "SENDER"
    mock_msg.receiver_id = "RECEIVER"
    mock_msg.connection_type = "API"
    mock_msg.status = "RECEIVED"
    mock_msg.edi_data = "raw edi payload"
    mock_msg.created_at = None
    mock_msg.trading_partner_id = None

    mock_json = MagicMock()
    mock_json.id = uuid.uuid4()
    mock_json.transaction_type = "850"

    mock_repo.get_transaction.return_value = TransactionDetailDTO(
        edi_message=mock_msg,
        edi_jsons=[mock_json],
        api_gateways=[],
    )

    mock_tenant_session = AsyncMock()
    mock_inbound_route = MagicMock()
    mock_inbound_route.webhook_id = uuid.uuid4()

    mock_tenant_execute = MagicMock()
    mock_tenant_execute.scalar_one_or_none.return_value = mock_inbound_route
    mock_tenant_scalars = MagicMock()
    mock_tenant_scalars.first.return_value = mock_inbound_route
    mock_tenant_execute.scalars.return_value = mock_tenant_scalars
    mock_tenant_session.execute.return_value = mock_tenant_execute

    mock_global_session = AsyncMock()
    mock_global_execute = MagicMock()
    mock_global_execute.scalar_one_or_none.return_value = "https://webhook.soopa.com"
    mock_global_scalars = MagicMock()
    mock_global_scalars.first.return_value = "https://webhook.soopa.com"
    mock_global_execute.scalars.return_value = mock_global_scalars
    mock_global_session.execute.return_value = mock_global_execute

    mock_uow = UnitOfWork(global_session=mock_global_session, tenant_session=mock_tenant_session)
    mock_uow._transactions = mock_repo

    app.dependency_overrides[get_tenant_uow] = lambda: mock_uow
    response = client.get(f"/api/v1/transactions/{mock_msg.trace_id}")
    assert response.status_code == 200
    assert response.json()["trading_partner_name"] == "https://webhook.soopa.com"
