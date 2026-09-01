import hashlib
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from identity.domain.constants import IdentityIdPrefix
from identity.domain.identity_context import M2M_API_KEY_PREFIX
from identity.domain.models.api_token import ApiTokenDomainModel
from seedwork.utils import generate_id

from ucp.application.use_cases.api_key_authenticator import (
    _token_cache,
    authenticate_api_key,
    invalidate_api_key_cache,
)
from ucp.testing.fakes import DummyApiTokenRepository


@pytest.fixture
def mock_token_repo():
    class TestApiTokenRepository(DummyApiTokenRepository):
        def __init__(self):
            self.tokens = {}

        async def get_by_client_id(self, client_id: str) -> ApiTokenDomainModel | None:
            return self.tokens.get(client_id)

    return TestApiTokenRepository()


@pytest.fixture(autouse=True)
def clear_cache():
    _token_cache.clear()
    yield
    _token_cache.clear()


@pytest.mark.asyncio
async def test_authenticate_api_key_success_and_cache(mock_token_repo):
    client_id = "test_client_id"
    client_secret = "test_client_secret"  # noqa: S105
    token = f"{M2M_API_KEY_PREFIX}{client_id}.{client_secret}"
    tenant_id = generate_id(IdentityIdPrefix.TENANT)
    token_id = generate_id(IdentityIdPrefix.TOKEN)

    secret_hash = hashlib.sha256(client_secret.encode("utf-8")).hexdigest()

    mock_token_repo.tokens[client_id] = ApiTokenDomainModel(
        id=token_id,
        tenant_id=tenant_id,
        client_id=client_id,
        secret_hash=secret_hash,
        name="Test Token",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        last_used_at=None,
        expires_at=None,
        active=True,
    )

    # First call - DB lookup
    identity = await authenticate_api_key(token, mock_token_repo)
    assert identity.subject == f"machine_{client_id}"
    assert identity.tenant_id == tenant_id
    assert tenant_id in identity.authorized_tenants
    assert "m2m_api_client" in identity.roles
    assert identity.claims["is_m2m"] is True

    assert client_id in _token_cache

    # Second call - Cache hit (prove it hits cache by removing from DB)
    del mock_token_repo.tokens[client_id]
    identity2 = await authenticate_api_key(token, mock_token_repo)
    assert identity2.tenant_id == tenant_id

    # Invalidate cache
    invalidate_api_key_cache(client_id)
    assert client_id not in _token_cache


@pytest.mark.asyncio
async def test_authenticate_api_key_invalid_prefix(mock_token_repo):
    with pytest.raises(HTTPException) as exc:
        await authenticate_api_key("wrong_prefix.client.secret", mock_token_repo)
    assert exc.value.status_code == 401
    assert exc.value.detail == "APIKEY_INVALID_PREFIX"


@pytest.mark.asyncio
async def test_authenticate_api_key_invalid_format(mock_token_repo):
    with pytest.raises(HTTPException) as exc:
        await authenticate_api_key(f"{M2M_API_KEY_PREFIX}invalid_format_no_dot", mock_token_repo)
    assert exc.value.status_code == 401
    assert exc.value.detail == "APIKEY_INVALID_FORMAT"


@pytest.mark.asyncio
async def test_authenticate_api_key_not_found(mock_token_repo):
    token = f"{M2M_API_KEY_PREFIX}unknown_client.secret"
    with pytest.raises(HTTPException) as exc:
        await authenticate_api_key(token, mock_token_repo)
    assert exc.value.status_code == 401
    assert exc.value.detail == "APIKEY_INVALID_OR_REVOKED"


@pytest.mark.asyncio
async def test_authenticate_api_key_wrong_secret(mock_token_repo):
    client_id = "test_client_id"
    token = f"{M2M_API_KEY_PREFIX}{client_id}.wrong_secret"
    token_id = generate_id(IdentityIdPrefix.TOKEN)
    tenant_id = generate_id(IdentityIdPrefix.TENANT)

    secret_hash = hashlib.sha256(b"correct_secret").hexdigest()

    mock_token_repo.tokens[client_id] = ApiTokenDomainModel(
        id=token_id,
        tenant_id=tenant_id,
        client_id=client_id,
        secret_hash=secret_hash,
        name="Test Token",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        last_used_at=None,
        expires_at=None,
        active=True,
    )

    with pytest.raises(HTTPException) as exc:
        await authenticate_api_key(token, mock_token_repo)
    assert exc.value.status_code == 401
    assert exc.value.detail == "APIKEY_INVALID_OR_REVOKED"
