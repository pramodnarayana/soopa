import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from api.dependencies import get_current_tenant_id, get_current_user_profile, get_tenant_uow
from api.main import app
from fastapi.testclient import TestClient


def override_get_current_user_profile():
    return {"sub": "test-user", "tenant_id": 1}


def override_get_current_tenant_id():
    return 1


mock_uow = AsyncMock()
mock_repo = AsyncMock()

mock_msg = MagicMock()
mock_msg.id = uuid.uuid4()
mock_msg.trace_id = uuid.uuid4()
mock_msg.direction = "INBOUND"
mock_msg.connection_type = "UNKNOWN"
mock_msg.sender_id = "A"
mock_msg.receiver_id = "B"
mock_msg.gs_sender_id = "A"
mock_msg.gs_receiver_id = "B"
mock_msg.status = "SUCCESS"
mock_msg.edi_data = "TEST"
mock_msg.created_at = datetime.now(UTC)
mock_msg.outbound_route_id = uuid.uuid4()

mock_json = MagicMock()
mock_json.id = uuid.uuid4()
mock_json.transaction_type = "850"
mock_json.sender_id = "A"
mock_json.receiver_id = "B"
mock_json.gs_sender_id = "A"
mock_json.gs_receiver_id = "B"
mock_json.business_metadata = {"_routing": {"trading_partner_id": str(uuid.uuid4())}}
mock_json.payload = "{}"
mock_json.status = "SUCCESS"
mock_json.created_at = datetime.now(UTC)

mock_gw = MagicMock()
mock_gw.id = uuid.uuid4()
mock_gw.webhook_url = "http://test"
mock_gw.http_status_code = 200
mock_gw.payload = "{}"
mock_gw.response = "{}"
mock_gw.status = "SUCCESS"
mock_gw.created_at = datetime.now(UTC)

mock_repo.list_transactions.return_value = [mock_msg]
mock_repo.get_transaction.return_value = {
    "edi_message": mock_msg,
    "edi_json": [mock_json],
    "api_gateway": [mock_gw],
}
mock_repo.get_transaction_thread.return_value = [mock_json]
mock_uow.data_plane = mock_repo

mock_route = MagicMock()
mock_route.as2_partner_id = uuid.uuid4()
mock_route.sftp_partner_id = None

mock_db_result = MagicMock()
mock_db_result.scalar_one_or_none.side_effect = [mock_route, "Test Partner"]

mock_uow.tenant_session = AsyncMock()
mock_uow.tenant_session.execute.return_value = mock_db_result

mock_uow.global_session = AsyncMock()
mock_uow.global_session.execute.return_value = mock_db_result

mock_uow.__aenter__.return_value = mock_uow


def override_get_tenant_uow():
    return mock_uow


@pytest.fixture(autouse=True)
def setup_dependencies():
    app.dependency_overrides[get_current_user_profile] = override_get_current_user_profile
    app.dependency_overrides[get_current_tenant_id] = override_get_current_tenant_id
    app.dependency_overrides[get_tenant_uow] = override_get_tenant_uow
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
    import uuid
    from unittest.mock import AsyncMock, MagicMock

    from api.dependencies import get_tenant_uow

    mock_uow.control_plane = AsyncMock()

    mock_msg = MagicMock()
    mock_msg.id = uuid.uuid4()
    mock_msg.trace_id = uuid.uuid4()
    mock_msg.outbound_route_id = uuid.uuid4()
    mock_msg.created_at = None

    mock_repo = AsyncMock()
    mock_repo.get_transaction.return_value = {
        "edi_message": mock_msg,
        "edi_json": [],
        "api_gateway": [],
    }
    mock_uow.data_plane = mock_repo

    mock_route = MagicMock()
    mock_route.as2_partner_id = None
    mock_route.sftp_partner_id = uuid.uuid4()

    mock_db_result = MagicMock()
    mock_db_result.scalar_one_or_none.side_effect = [mock_route, "SFTP Partner"]

    mock_uow.tenant_session = AsyncMock()
    mock_uow.tenant_session.execute.return_value = mock_db_result

    mock_uow.global_session = AsyncMock()
    mock_uow.global_session.execute.return_value = mock_db_result

    mock_uow.__aenter__.return_value = mock_uow

    app.dependency_overrides[get_tenant_uow] = lambda: mock_uow
    response = client.get(f"/api/v1/transactions/{mock_msg.trace_id}")
    assert response.status_code == 200
    assert response.json()["trading_partner_name"] == "SFTP Partner"


def test_get_transaction_detail_fallback():
    import uuid
    from unittest.mock import AsyncMock, MagicMock

    from api.dependencies import get_tenant_uow

    mock_uow.control_plane = AsyncMock()

    mock_msg = MagicMock()
    mock_msg.id = uuid.uuid4()
    mock_msg.trace_id = uuid.uuid4()
    mock_msg.outbound_route_id = None
    mock_msg.created_at = None

    mock_json = MagicMock()
    mock_json.id = uuid.uuid4()
    mock_json.created_at = None
    mock_json.business_metadata = {"_routing": {"trading_partner_id": str(uuid.uuid4())}}

    mock_repo = AsyncMock()
    mock_repo.get_transaction.return_value = {
        "edi_message": mock_msg,
        "edi_json": [mock_json],
        "api_gateway": [],
    }
    mock_uow.data_plane = mock_repo

    mock_db_result = MagicMock()
    # first call returns None (AS2Partner lookup misses), second returns "Fallback Partner" (SFTPPartner lookup hits)
    mock_db_result.scalar_one_or_none.side_effect = [None, "Fallback Partner"]

    mock_uow.global_session = AsyncMock()
    mock_uow.global_session.execute.return_value = mock_db_result
    mock_uow.__aenter__.return_value = mock_uow

    app.dependency_overrides[get_tenant_uow] = lambda: mock_uow
    response = client.get(f"/api/v1/transactions/{mock_msg.trace_id}")
    assert response.status_code == 200
    assert response.json()["trading_partner_name"] == "Fallback Partner"


def test_get_transaction_not_found():
    import uuid
    from unittest.mock import AsyncMock

    from api.dependencies import get_tenant_uow

    mock_uow.control_plane = AsyncMock()

    mock_repo = AsyncMock()
    mock_repo.get_transaction.return_value = None
    mock_uow.data_plane = mock_repo

    app.dependency_overrides[get_tenant_uow] = lambda: mock_uow
    uid = str(uuid.uuid4())
    response = client.get(f"/api/v1/transactions/{uid}")
    assert response.status_code == 404


def test_get_transaction_webhook_fallback():
    import uuid
    from unittest.mock import AsyncMock, MagicMock

    from api.dependencies import get_tenant_uow

    mock_uow = MagicMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)
    mock_uow.control_plane = AsyncMock()

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
    mock_msg.outbound_route_id = None

    mock_json = MagicMock()
    mock_json.id = uuid.uuid4()
    mock_json.transaction_type = "850"

    mock_repo.get_transaction.return_value = {
        "edi_message": mock_msg,
        "edi_json": [mock_json],
        "api_gateway": [],
    }
    mock_uow.data_plane = mock_repo

    mock_tenant_session = AsyncMock()
    mock_inbound_route = MagicMock()
    mock_inbound_route.webhook_id = uuid.uuid4()

    mock_tenant_execute = MagicMock()
    mock_tenant_execute.scalar_one_or_none.return_value = mock_inbound_route
    mock_tenant_session.execute.return_value = mock_tenant_execute
    mock_uow.tenant_session = mock_tenant_session

    mock_global_session = AsyncMock()
    mock_global_execute = MagicMock()
    mock_global_execute.scalar_one_or_none.return_value = "https://webhook.soopa.com"
    mock_global_session.execute.return_value = mock_global_execute
    mock_uow.global_session = mock_global_session

    app.dependency_overrides[get_tenant_uow] = lambda: mock_uow
    response = client.get(f"/api/v1/transactions/{mock_msg.trace_id}")
    assert response.status_code == 200
    assert response.json()["trading_partner_name"] == "Webhook: https://webhook.soopa.com"
