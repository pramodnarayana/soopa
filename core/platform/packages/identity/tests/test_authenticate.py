from unittest.mock import AsyncMock

import pytest

from identity.application.authenticate import AuthenticationError, authenticate_bearer_token
from identity.domain.identity_context import IdentityContext, TokenClaims
from identity.ports.token_verifier import TokenVerifier


@pytest.fixture
def mock_verifier() -> AsyncMock:
    return AsyncMock(spec=TokenVerifier)


@pytest.mark.asyncio
async def test_authenticate_bearer_token_valid(mock_verifier: AsyncMock) -> None:
    claims = TokenClaims(
        sub="user-123",
        iss="https://auth.example.com",
        aud="api",
        exp=1700000000,
        tenant_id="tenant-123",
        roles=["admin"],
    )
    mock_verifier.verify.return_value = claims

    context = await authenticate_bearer_token("Bearer valid.jwt.token", mock_verifier)

    assert isinstance(context, IdentityContext)
    assert context.subject == "user-123"
    assert context.tenant_id == "tenant-123"

    mock_verifier.verify.assert_called_once_with("valid.jwt.token")


@pytest.mark.asyncio
async def test_authenticate_bearer_token_missing_header(mock_verifier: AsyncMock) -> None:
    with pytest.raises(AuthenticationError, match="Missing bearer token"):
        await authenticate_bearer_token(None, mock_verifier)
    mock_verifier.verify.assert_not_called()


@pytest.mark.asyncio
async def test_authenticate_bearer_token_empty_token(mock_verifier: AsyncMock) -> None:
    with pytest.raises(AuthenticationError, match="Empty bearer token"):
        await authenticate_bearer_token("Bearer ", mock_verifier)
    mock_verifier.verify.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "header", ["bearer valid.jwt.token", "BEARER valid.jwt.token", "bEaReR valid.jwt.token"]
)
async def test_authenticate_bearer_token_case_insensitive(
    mock_verifier: AsyncMock, header: str
) -> None:
    claims = TokenClaims(
        sub="user-123",
        iss="https://auth.example.com",
        aud="api",
        exp=1700000000,
        tenant_id="tenant-123",
        roles=["admin"],
    )
    mock_verifier.verify.return_value = claims

    context = await authenticate_bearer_token(header, mock_verifier)

    assert context.subject == "user-123"
    mock_verifier.verify.assert_called_once_with("valid.jwt.token")


@pytest.mark.asyncio
async def test_authenticate_bearer_token_invalid_format(mock_verifier: AsyncMock) -> None:
    from identity.ports.token_verifier import TokenValidationError

    mock_verifier.verify.side_effect = TokenValidationError("Bad signature")

    with pytest.raises(AuthenticationError, match="Invalid token format or signature"):
        await authenticate_bearer_token("Bearer invalid.token", mock_verifier)
