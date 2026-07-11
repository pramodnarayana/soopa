from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from api.core.services.api_token_service import ApiTokenService, _generate_credentials
from api.domain.models import CreateApiTokenCmd


@pytest.mark.asyncio
async def test_api_token_service_create():
    mock_repo = AsyncMock()
    token_id = uuid4()
    mock_repo.create_api_token.return_value = token_id

    svc = ApiTokenService(mock_repo)
    cmd = CreateApiTokenCmd(name="Test Token", expires_at=None)

    result = await svc.create_token(tenant_id=1, tenant_name="Acme Corp", cmd=cmd)

    assert result.id == token_id
    assert result.tenant_id == 1
    assert result.name == "Test Token"
    assert result.client_id.startswith("soopaedi_acmeco_")
    assert len(result.client_secret) > 0
    assert result.active is True

    mock_repo.create_api_token.assert_awaited_once()


@pytest.mark.asyncio
async def test_api_token_service_list():
    mock_repo = AsyncMock()
    mock_repo.list_api_tokens.return_value = [{"id": str(uuid4())}]

    svc = ApiTokenService(mock_repo)
    result = await svc.list_tokens(tenant_id=1)

    assert len(result) == 1
    mock_repo.list_api_tokens.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_api_token_service_revoke():
    mock_repo = AsyncMock()
    mock_repo.revoke_api_token.return_value = True

    svc = ApiTokenService(mock_repo)
    t_id = uuid4()
    result = await svc.revoke_token(tenant_id=1, token_id=t_id)

    assert result is True
    mock_repo.revoke_api_token.assert_awaited_once_with(1, t_id)


@pytest.mark.asyncio
async def test_api_token_service_delete():
    mock_repo = AsyncMock()
    mock_repo.delete_api_token.return_value = True

    svc = ApiTokenService(mock_repo)
    t_id = uuid4()
    result = await svc.delete_token(tenant_id=1, token_id=t_id)

    assert result is True
    mock_repo.delete_api_token.assert_awaited_once_with(1, t_id)


def test_generate_credentials():
    c_id, c_secret, c_hash = _generate_credentials("TestTenant123")
    assert c_id.startswith("soopaedi_testte_")
    assert len(c_secret) > 32
    assert len(c_hash) == 64
