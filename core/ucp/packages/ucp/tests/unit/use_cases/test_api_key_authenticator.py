import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from identity.application.authenticate_use_case import AuthenticationError
from identity.domain.api_token import ApiToken
from identity.domain.identity_context import M2M_API_KEY_PREFIX
from seedwork.utils import generate_id

from ucp.application.use_cases.api_key_authenticator import (
    _token_cache,
    authenticate_api_key,
    invalidate_api_key_cache,
)
from ucp.application.use_cases.api_tokens.delete_api_token_use_case import DeleteApiTokenUseCase
from ucp.application.use_cases.api_tokens.update_api_token_use_case import (
    UpdateApiTokenCommand,
    UpdateApiTokenUseCase,
)
from ucp.domain.constants import UcpIdPrefix as DomainIdPrefix
from ucp.testing.fakes import DummyApiTokenRepository, FakeUcpUnitOfWork


@pytest.fixture
def fake_token_repo():
    class TestApiTokenRepository(DummyApiTokenRepository):
        def __init__(self):
            self.tokens = {}

        async def get_by_client_id(self, client_id: str) -> ApiToken | None:
            return self.tokens.get(client_id)

    return TestApiTokenRepository()


@pytest.fixture(autouse=True)
def clear_cache():
    _token_cache.clear()
    yield
    _token_cache.clear()


@pytest.mark.asyncio
async def test_authenticate_api_key_success_and_cache(fake_token_repo):
    client_id = "test_client_id"
    client_key_val = "test_client_secret"
    token = f"{M2M_API_KEY_PREFIX}{client_id}.{client_key_val}"
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    token_id = generate_id(DomainIdPrefix.TOKEN)

    secret_hash = hashlib.sha256(client_key_val.encode("utf-8")).hexdigest()

    fake_token_repo.tokens[client_id] = ApiToken(
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
    identity = await authenticate_api_key(token, fake_token_repo)
    assert identity.subject == f"machine_{client_id}"
    assert identity.tenant_id == tenant_id
    assert tenant_id in identity.authorized_tenants
    assert "m2m_api_client" in identity.roles
    assert identity.claims["is_m2m"] is True

    assert client_id in _token_cache

    # Second call - Cache hit (prove it hits cache by removing from DB)
    del fake_token_repo.tokens[client_id]
    identity2 = await authenticate_api_key(token, fake_token_repo)
    assert identity2.tenant_id == tenant_id

    # Invalidate cache
    invalidate_api_key_cache(client_id)
    assert client_id not in _token_cache


@pytest.mark.asyncio
async def test_authenticate_api_key_invalid_prefix(fake_token_repo):
    with pytest.raises(AuthenticationError) as exc:
        await authenticate_api_key("wrong_prefix.client.secret", fake_token_repo)

    assert str(exc.value) == "APIKEY_INVALID_PREFIX"


@pytest.mark.asyncio
async def test_authenticate_api_key_invalid_format(fake_token_repo):
    with pytest.raises(AuthenticationError) as exc:
        await authenticate_api_key(f"{M2M_API_KEY_PREFIX}invalid_format_no_dot", fake_token_repo)

    assert str(exc.value) == "APIKEY_INVALID_FORMAT"


@pytest.mark.asyncio
async def test_authenticate_api_key_not_found(fake_token_repo):
    token = f"{M2M_API_KEY_PREFIX}unknown_client.secret"
    with pytest.raises(AuthenticationError) as exc:
        await authenticate_api_key(token, fake_token_repo)

    assert str(exc.value) == "APIKEY_INVALID_OR_REVOKED"


@pytest.mark.asyncio
async def test_authenticate_api_key_wrong_secret(fake_token_repo):
    client_id = "test_client_id"
    token = f"{M2M_API_KEY_PREFIX}{client_id}.wrong_secret"
    token_id = generate_id(DomainIdPrefix.TOKEN)
    tenant_id = generate_id(DomainIdPrefix.TENANT)

    secret_hash = hashlib.sha256(b"correct_secret").hexdigest()

    fake_token_repo.tokens[client_id] = ApiToken(
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

    with pytest.raises(AuthenticationError) as exc:
        await authenticate_api_key(token, fake_token_repo)

    assert str(exc.value) == "APIKEY_INVALID_OR_REVOKED"


@pytest.mark.asyncio
async def test_authenticate_api_key_rejects_expired_token_on_db_lookup(fake_token_repo):
    now = datetime.now(UTC)
    client_id = "expired_db_client"
    raw_secret = secrets.token_hex(16)
    token = f"{M2M_API_KEY_PREFIX}{client_id}.{raw_secret}"
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    token_id = generate_id(DomainIdPrefix.TOKEN)
    secret_hash = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()

    fake_token_repo.tokens[client_id] = ApiToken(
        id=token_id,
        tenant_id=tenant_id,
        client_id=client_id,
        secret_hash=secret_hash,
        name="Already Expired Token",
        created_at=now - timedelta(hours=2),
        updated_at=now - timedelta(hours=2),
        last_used_at=None,
        expires_at=now - timedelta(seconds=1),
        active=True,
    )

    with pytest.raises(AuthenticationError) as exc:
        await authenticate_api_key(token, fake_token_repo, now=now)

    assert str(exc.value) == "APIKEY_INVALID_OR_REVOKED"
    assert client_id not in _token_cache


@pytest.mark.asyncio
async def test_authenticate_api_key_rejects_expired_token_on_cache_hit_and_evicts(fake_token_repo):
    now = datetime.now(UTC)
    client_id = "expiring_cached_client"
    raw_secret = secrets.token_hex(16)
    token = f"{M2M_API_KEY_PREFIX}{client_id}.{raw_secret}"
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    token_id = generate_id(DomainIdPrefix.TOKEN)
    secret_hash = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()
    expires_at = now + timedelta(minutes=5)

    fake_token_repo.tokens[client_id] = ApiToken(
        id=token_id,
        tenant_id=tenant_id,
        client_id=client_id,
        secret_hash=secret_hash,
        name="Short-Lived Token",
        created_at=now,
        updated_at=now,
        last_used_at=None,
        expires_at=expires_at,
        active=True,
    )

    # Initial DB lookup succeeds before expiry and populates cache
    first_identity = await authenticate_api_key(token, fake_token_repo, now=now)
    assert first_identity.tenant_id == tenant_id
    assert client_id in _token_cache

    # Remove DB record to prove subsequent unexpired check comes from cache
    del fake_token_repo.tokens[client_id]
    cached_identity = await authenticate_api_key(
        token, fake_token_repo, now=now + timedelta(minutes=4)
    )
    assert cached_identity.tenant_id == tenant_id

    # At exact expiry timestamp (and after), cache-hit path must reject and evict
    with pytest.raises(AuthenticationError) as exc:
        await authenticate_api_key(token, fake_token_repo, now=expires_at)

    assert str(exc.value) == "APIKEY_INVALID_OR_REVOKED"
    assert client_id not in _token_cache


@pytest.mark.asyncio
async def test_revoke_and_delete_use_cases_evict_api_key_cache() -> None:
    uow = FakeUcpUnitOfWork()
    now = datetime.now(UTC)
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    client_id = "revocable_client"
    raw_secret = secrets.token_hex(16)
    raw_key = f"{M2M_API_KEY_PREFIX}{client_id}.{raw_secret}"
    secret_hash = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()

    seeded = ApiToken.create(
        tenant_id=tenant_id,
        name="Revocable Token",
        client_id=client_id,
        secret_hash=secret_hash,
        expires_at=now + timedelta(hours=1),
    ).unwrap()
    await uow.api_token_repo.save(seeded)

    await authenticate_api_key(raw_key, uow.api_token_repo, now=now)
    assert client_id in _token_cache

    revoke_uc = UpdateApiTokenUseCase(uow=uow)
    revoke_res = await revoke_uc.execute(
        token_id=seeded.id,
        tenant_id=tenant_id,
        command=UpdateApiTokenCommand(active=False),
    )
    assert revoke_res.is_ok
    assert client_id not in _token_cache

    # Re-activate, re-cache, then delete and verify cache eviction
    assert (
        await revoke_uc.execute(
            token_id=seeded.id,
            tenant_id=tenant_id,
            command=UpdateApiTokenCommand(active=True),
        )
    ).is_ok
    await authenticate_api_key(raw_key, uow.api_token_repo, now=now)
    assert client_id in _token_cache

    delete_uc = DeleteApiTokenUseCase(uow=uow)
    assert (await delete_uc.execute(token_id=seeded.id, tenant_id=tenant_id)).is_ok
    assert client_id not in _token_cache
