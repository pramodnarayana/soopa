from collections.abc import AsyncGenerator, Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from identity.dependencies import (
    get_current_tenant_id,
    get_raw_jwt,
    get_tenant_session,
)


@pytest.fixture(autouse=True)
def mock_httpx_client() -> Iterator[MagicMock]:
    with patch("identity.dependencies.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        yield mock_client


@pytest.mark.asyncio
async def test_get_raw_jwt_valid(mock_httpx_client: AsyncMock) -> None:
    payload = {"sub": "user123", "email": "pramod.narayana@gmail.com", "org_id": "org-123"}
    mock_response = MagicMock()
    mock_response.json.return_value = payload
    mock_httpx_client.get.return_value = mock_response

    decoded = await get_raw_jwt("fake.jwt.token")
    assert decoded["email"] == "pramod.narayana@gmail.com"
    assert decoded["sub"] == "user123"


@pytest.mark.asyncio
async def test_get_raw_jwt_missing() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_raw_jwt(None)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_raw_jwt_invalid(mock_httpx_client: AsyncMock) -> None:
    import httpx

    mock_httpx_client.get.side_effect = httpx.HTTPError("Invalid request")
    with pytest.raises(HTTPException) as exc_info:
        await get_raw_jwt("invalid.token.structure")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_tenant_id_success() -> None:
    mock_use_case = AsyncMock()
    mock_use_case.execute.return_value = 99

    token_payload = {"email": "pramod.narayana@gmail.com", "name": "Pramod"}

    tenant_id = await get_current_tenant_id(token_payload, mock_use_case)
    assert tenant_id == 99
    mock_use_case.execute.assert_called_once_with("pramod.narayana@gmail.com", "Pramod")


@pytest.mark.asyncio
async def test_get_current_tenant_id_missing_email() -> None:
    mock_use_case = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await get_current_tenant_id({"sub": "123"}, mock_use_case)
    assert exc_info.value.status_code == 403
    assert "email claim" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_get_current_tenant_id_value_error() -> None:
    mock_use_case = AsyncMock()
    mock_use_case.execute.side_effect = ValueError("User exists but is not mapped")

    with pytest.raises(HTTPException) as exc_info:
        await get_current_tenant_id({"email": "test-org@example.com"}, mock_use_case)

    assert exc_info.value.status_code == 403
    assert "is not mapped" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_get_current_tenant_id_runtime_error() -> None:
    mock_use_case = AsyncMock()
    mock_use_case.execute.side_effect = RuntimeError("Default shard not found")

    with pytest.raises(HTTPException) as exc_info:
        await get_current_tenant_id({"email": "test-org@example.com"}, mock_use_case)

    assert exc_info.value.status_code == 500
    assert "Default shard" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_get_tenant_session() -> None:
    mock_request = MagicMock(spec=Request)
    mock_db_router = AsyncMock()
    mock_request.app.state.db_router = mock_db_router

    # Mock Global Session fetch
    mock_global_session = AsyncMock()
    mock_tenant = MagicMock()
    mock_shard = MagicMock()
    mock_shard.name = "shard_1"
    mock_shard.dsn = "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1"
    mock_result = MagicMock()
    mock_result.one.return_value = (mock_tenant, mock_shard)
    mock_global_session.execute.return_value = mock_result

    async def mock_global_session_gen() -> AsyncGenerator[AsyncMock, None]:
        yield mock_global_session

    mock_db_router.get_global_session = MagicMock(return_value=mock_global_session_gen())

    # Mock Tenant Session fetch
    mock_tenant_session = AsyncMock()

    async def mock_tenant_session_gen() -> AsyncGenerator[AsyncMock, None]:
        yield mock_tenant_session

    mock_db_router.get_tenant_session = MagicMock(return_value=mock_tenant_session_gen())

    gen = get_tenant_session(mock_request, tenant_id=99, global_session=mock_global_session)
    session = await gen.__anext__()

    assert session == mock_tenant_session
    mock_db_router.get_tenant_session.assert_called_once_with(
        99, "shard_1", "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1"
    )
