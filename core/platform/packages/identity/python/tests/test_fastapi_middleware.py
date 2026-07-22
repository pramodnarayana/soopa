from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from soopa_identity.application.authenticate import AuthenticationError
from soopa_identity.domain.identity_context import IdentityContext
from soopa_identity.middleware.fastapi import (
    attach_identity_to_request,
    identity_dependency,
    require_identity,
)


@pytest.fixture
def mock_verifier() -> AsyncMock:
    return AsyncMock()


@pytest.mark.asyncio
@patch("soopa_identity.middleware.fastapi.authenticate_bearer_token")
async def test_identity_dependency_success(
    mock_authenticate: AsyncMock, mock_verifier: AsyncMock
) -> None:
    mock_context = IdentityContext(
        subject="user-1",
        tenant_id="tenant-1",
        claims={},
    )
    mock_authenticate.return_value = mock_context

    dep = identity_dependency(mock_verifier)

    # We call the returned async function directly
    result = await dep("Bearer valid")

    assert result == mock_context
    mock_authenticate.assert_called_once_with("Bearer valid", mock_verifier)


@pytest.mark.asyncio
@patch("soopa_identity.middleware.fastapi.authenticate_bearer_token")
async def test_identity_dependency_error(
    mock_authenticate: AsyncMock, mock_verifier: AsyncMock
) -> None:
    mock_authenticate.side_effect = AuthenticationError("Bad token")

    dep = identity_dependency(mock_verifier)

    with pytest.raises(HTTPException) as exc_info:
        await dep("Bearer bad")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Bad token"


def test_require_identity(mock_verifier: AsyncMock) -> None:
    depends = require_identity(mock_verifier)
    # Fastapi Depends object returned
    assert depends is not None


@pytest.mark.asyncio
@patch("soopa_identity.middleware.fastapi.authenticate_bearer_token")
async def test_attach_identity_to_request(
    mock_authenticate: AsyncMock, mock_verifier: AsyncMock
) -> None:
    mock_context = IdentityContext(
        subject="user-1",
        tenant_id="tenant-1",
        claims={},
    )
    mock_authenticate.return_value = mock_context


    mock_request = MagicMock()
    mock_request.headers.get.return_value = "Bearer valid"

    await attach_identity_to_request(mock_request, mock_verifier)

    assert mock_request.state.identity == mock_context
    mock_request.headers.get.assert_called_once_with("authorization")
    mock_authenticate.assert_called_once_with("Bearer valid", mock_verifier)
