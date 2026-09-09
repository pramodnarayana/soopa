import pytest

from identity.application.authenticate_use_case import (
    AuthenticateCommand,
    AuthenticationError,
    authenticate_bearer_token,
)
from identity.domain.identity_context import IdentityContext, TokenClaims
from identity.testing.fakes.fake_token_verifier import FakeTokenVerifier


@pytest.fixture
def fake_verifier() -> FakeTokenVerifier:
    return FakeTokenVerifier()


@pytest.mark.asyncio
async def test_authenticate_bearer_token_valid(fake_verifier: FakeTokenVerifier) -> None:
    claims = TokenClaims(
        sub="user-123",
        iss="https://auth.example.com",
        aud="api",
        exp=1700000000,
        tenant_id="tenant-123",
        roles=["admin"],
    )
    fake_verifier.given_valid_token("valid.jwt.token", claims)

    command = AuthenticateCommand(authorization_header="Bearer valid.jwt.token")
    context = await authenticate_bearer_token(command, fake_verifier)

    assert isinstance(context, IdentityContext)
    assert context.subject == "user-123"
    assert context.tenant_id == "tenant-123"

    assert "valid.jwt.token" in fake_verifier.verified_calls


@pytest.mark.asyncio
async def test_authenticate_bearer_token_missing_header(fake_verifier: FakeTokenVerifier) -> None:
    command = AuthenticateCommand(authorization_header=None)
    with pytest.raises(AuthenticationError, match=r"Missing bearer token\."):
        await authenticate_bearer_token(command, fake_verifier)
    assert len(fake_verifier.verified_calls) == 0


@pytest.mark.asyncio
async def test_authenticate_bearer_token_empty_token(fake_verifier: FakeTokenVerifier) -> None:
    command = AuthenticateCommand(authorization_header="Bearer ")
    with pytest.raises(AuthenticationError, match=r"Empty bearer token\."):
        await authenticate_bearer_token(command, fake_verifier)
    assert len(fake_verifier.verified_calls) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "header", ["bearer valid.jwt.token", "BEARER valid.jwt.token", "bEaReR valid.jwt.token"]
)
async def test_authenticate_bearer_token_case_insensitive(
    fake_verifier: FakeTokenVerifier, header: str
) -> None:
    claims = TokenClaims(
        sub="user-123",
        iss="https://auth.example.com",
        aud="api",
        exp=1700000000,
        tenant_id="tenant-123",
        roles=["admin"],
    )
    fake_verifier.given_valid_token("valid.jwt.token", claims)

    command = AuthenticateCommand(authorization_header=header)
    context = await authenticate_bearer_token(command, fake_verifier)

    assert context.subject == "user-123"
    assert "valid.jwt.token" in fake_verifier.verified_calls


@pytest.mark.asyncio
async def test_authenticate_bearer_token_invalid_format(fake_verifier: FakeTokenVerifier) -> None:
    fake_verifier.given_invalid_format_error()

    with pytest.raises(
        AuthenticationError, match="Authentication failed: Invalid token format or signature"
    ):
        command = AuthenticateCommand(authorization_header="Bearer invalid.token")
        await authenticate_bearer_token(command, fake_verifier)
