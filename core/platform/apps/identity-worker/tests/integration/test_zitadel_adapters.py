from unittest.mock import AsyncMock, patch

import httpx
import pytest
from identity_worker.adapters.outbound.identity_provider.zitadel_organizations_adapter import (
    ZitadelOrganizationsAdapter,
)
from identity_worker.adapters.outbound.identity_provider.zitadel_projects_adapter import (
    ZitadelProjectsAdapter,
)
from identity_worker.adapters.outbound.identity_provider.zitadel_users_adapter import (
    ZitadelUsersAdapter,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_httpx_request():
    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        yield mock_req


@pytest.fixture
def mock_project_provider():
    provider = AsyncMock(spec=ZitadelProjectsAdapter)
    provider.ucp_project_id = "test-ucp-project-id"
    provider.get_roles.return_value = []
    return provider


async def test_create_organization_success(mock_httpx_request, mock_project_provider, monkeypatch):
    monkeypatch.setenv("ZITADEL_API_TOKEN", "fake_token")
    monkeypatch.setenv("ZITADEL_UCP_PROJECT_ID", "fake_proj_id")
    # Refresh settings to pick up env vars if needed, though they might be cached
    # For now assume ZitadelClient will have a token if we set it, or we just patch the config.
    adapter = ZitadelOrganizationsAdapter(mock_project_provider)
    adapter.token = "fake_token"  # noqa: S105
    adapter.ucp_project_id = "fake_proj_id"

    mock_resp = httpx.Response(200, json={"id": "new-org-id"})
    mock_httpx_request.return_value = mock_resp

    org_id, _ = await adapter.create_organization("Test Org")

    assert org_id == "new-org-id"
    # Ensure correct HTTP call was made
    mock_httpx_request.assert_called_once()
    args, kwargs = mock_httpx_request.call_args
    assert args[0] == "POST"
    assert "management/v1/orgs" in args[1]
    assert kwargs["json"] == {"name": "Test Org"}
    assert kwargs["headers"]["Authorization"] == "Bearer fake_token"


async def test_create_user_success(mock_httpx_request):
    adapter = ZitadelUsersAdapter()
    adapter.token = "fake_token"  # noqa: S105
    adapter.ucp_project_id = "fake_proj_id"

    # Mocking two endpoints: user creation and then _get_project_grant_id
    mock_user_resp = httpx.Response(200, json={"userId": "new-user-id"})

    mock_httpx_request.return_value = mock_user_resp

    user_id = await adapter.create_user(
        org_id="org-123", email="test@test.com", first_name="First", last_name="Last"
    )

    assert user_id == "new-user-id"

    # Check that HTTP payload was constructed exactly as expected
    args, kwargs = mock_httpx_request.call_args
    assert args[0] == "POST"
    assert "management/v1/users/human" in args[1]
    assert kwargs["headers"]["x-zitadel-orgid"] == "org-123"
    assert kwargs["json"]["profile"]["firstName"] == "First"
    assert kwargs["json"]["profile"]["lastName"] == "Last"
    assert kwargs["json"]["email"]["email"] == "test@test.com"


async def test_delete_user_idempotent(mock_httpx_request):
    adapter = ZitadelUsersAdapter()
    adapter.token = "fake_token"  # noqa: S105
    adapter.ucp_project_id = "fake_proj_id"

    # Simulate user already deleted (404)
    mock_resp = httpx.Response(404, json={})
    mock_httpx_request.return_value = mock_resp

    # Should not raise exception
    await adapter.delete_user("user-404")

    args, _ = mock_httpx_request.call_args
    assert args[0] == "DELETE"
    assert "management/v1/users/user-404" in args[1]
