from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from identity.adapters.inbound.http.fastapi_middleware import (
    attach_identity_to_request,
    identity_dependency,
    require_identity,
)
from identity.application.authenticate_use_case import AuthenticationError
from identity.domain.identity_context import IdentityContext, TokenClaims
from tests.fakes.fake_token_verifier import FakeTokenVerifier


class FakeHeaders:
    def __init__(self, headers: dict[str, str]) -> None:
        self._headers = headers

    def get(self, key: str) -> str | None:
        return self._headers.get(key)


class FakeRequest:
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = FakeHeaders(headers or {})
        self.state = SimpleNamespace()


@pytest.fixture
def fake_verifier() -> FakeTokenVerifier:
    verifier = FakeTokenVerifier()
    claims = TokenClaims(
        sub="user-1",
        iss="https://auth.example.com",
        aud="api",
        exp=1700000000,
        tenant_id="tenant-1",
        roles=["admin"],
    )
    verifier.given_valid_token("valid", claims)
    return verifier


@pytest.mark.asyncio
async def test_identity_dependency_success(fake_verifier: FakeTokenVerifier) -> None:
    dep = identity_dependency(fake_verifier)

    # We call the returned async function directly
    result = await dep("Bearer valid")

    assert isinstance(result, IdentityContext)
    assert result.subject == "user-1"
    assert result.tenant_id == "tenant-1"
    assert "valid" in fake_verifier.verified_calls


@pytest.mark.asyncio
async def test_identity_dependency_error(fake_verifier: FakeTokenVerifier) -> None:
    dep = identity_dependency(fake_verifier)

    with pytest.raises(HTTPException) as exc_info:
        await dep("Bearer bad")

    assert exc_info.value.status_code == 401
    assert (
        "Authentication failed: Signature has expired or token is invalid" in exc_info.value.detail
    )


def test_require_identity(fake_verifier: FakeTokenVerifier) -> None:
    depends = require_identity(fake_verifier)
    # Fastapi Depends object returned
    assert depends is not None


@pytest.mark.asyncio
async def test_attach_identity_to_request(fake_verifier: FakeTokenVerifier) -> None:
    fake_request = FakeRequest(headers={"authorization": "Bearer valid"})

    await attach_identity_to_request(fake_request, fake_verifier)  # type: ignore

    assert hasattr(fake_request.state, "identity")
    assert isinstance(fake_request.state.identity, IdentityContext)
    assert fake_request.state.identity.subject == "user-1"


@pytest.mark.asyncio
async def test_attach_identity_to_request_raises_auth_error(
    fake_verifier: FakeTokenVerifier,
) -> None:
    fake_request = FakeRequest(headers={"authorization": "Bearer invalid"})

    with pytest.raises(AuthenticationError):
        await attach_identity_to_request(fake_request, fake_verifier)  # type: ignore

    assert not hasattr(fake_request.state, "identity")
