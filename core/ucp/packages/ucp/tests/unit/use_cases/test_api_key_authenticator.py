import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from identity.application.authenticate_use_case import AuthenticationError
from identity.domain.api_token import ApiToken
from identity.domain.identity_context import M2M_API_KEY_PREFIX
from seedwork.utils import generate_id

from ucp.application.use_cases import api_key_authenticator
from ucp.application.use_cases.api_key_authenticator import authenticate_api_key
from ucp.application.use_cases.api_tokens.delete_api_token_use_case import DeleteApiTokenUseCase
from ucp.application.use_cases.api_tokens.update_api_token_use_case import (
    UpdateApiTokenCommand,
    UpdateApiTokenUseCase,
)
from ucp.domain.constants import UcpIdPrefix as DomainIdPrefix
from ucp.testing.fakes import DummyApiTokenRepository, FakeUcpUnitOfWork


class SharedTestApiTokenRepository(DummyApiTokenRepository):
    """In-memory repository representing authoritative shared database state."""

    def __init__(self) -> None:
        super().__init__()
        self.tokens_by_client_id: dict[str, ApiToken] = {}

    async def get_by_client_id(self, client_id: str) -> ApiToken | None:
        token = self.tokens_by_client_id.get(client_id)
        if token is None or not token.active or token.is_expired():
            return None
        return token


@pytest.fixture
def fake_token_repo() -> SharedTestApiTokenRepository:
    return SharedTestApiTokenRepository()


def test_authenticator_has_zero_process_local_mutable_cache() -> None:
    assert not hasattr(api_key_authenticator, "_token_cache")
    assert not hasattr(api_key_authenticator, "invalidate_api_key_cache")


@pytest.mark.asyncio
async def test_authenticate_api_key_success_and_shared_state_revocation(
    fake_token_repo: SharedTestApiTokenRepository,
) -> None:
    client_id = "test_client_id"
    raw_secret = secrets.token_hex(16)
    token = f"{M2M_API_KEY_PREFIX}{client_id}.{raw_secret}"
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    token_id = generate_id(DomainIdPrefix.TOKEN)
    secret_hash = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()

    fake_token_repo.tokens_by_client_id[client_id] = ApiToken(
        id=token_id,
        tenant_id=tenant_id,
        client_id=client_id,
        secret_hash=secret_hash,
        name="Non-Expiring Shared Token",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        last_used_at=None,
        expires_at=None,
        active=True,
    )

    identity = await authenticate_api_key(token, fake_token_repo)
    assert identity.subject == f"machine_{client_id}"
    assert identity.tenant_id == tenant_id
    assert tenant_id in identity.authorized_tenants
    assert "m2m_api_client" in identity.roles
    assert identity.claims["is_m2m"] is True

    # Simulate revocation on another API replica mutating shared DB state directly
    fake_token_repo.tokens_by_client_id[client_id].revoke()

    with pytest.raises(AuthenticationError) as exc:
        await authenticate_api_key(token, fake_token_repo)
    assert str(exc.value) == "APIKEY_INVALID_OR_REVOKED"


@pytest.mark.asyncio
async def test_authenticate_api_key_invalid_prefix(
    fake_token_repo: SharedTestApiTokenRepository,
) -> None:
    with pytest.raises(AuthenticationError) as exc:
        await authenticate_api_key("wrong_prefix.client.secret", fake_token_repo)

    assert str(exc.value) == "APIKEY_INVALID_PREFIX"


@pytest.mark.asyncio
async def test_authenticate_api_key_invalid_format(
    fake_token_repo: SharedTestApiTokenRepository,
) -> None:
    with pytest.raises(AuthenticationError) as exc:
        await authenticate_api_key(f"{M2M_API_KEY_PREFIX}invalid_format_no_dot", fake_token_repo)

    assert str(exc.value) == "APIKEY_INVALID_FORMAT"


@pytest.mark.asyncio
async def test_authenticate_api_key_not_found(
    fake_token_repo: SharedTestApiTokenRepository,
) -> None:
    token = f"{M2M_API_KEY_PREFIX}unknown_client.secret"
    with pytest.raises(AuthenticationError) as exc:
        await authenticate_api_key(token, fake_token_repo)

    assert str(exc.value) == "APIKEY_INVALID_OR_REVOKED"


@pytest.mark.asyncio
async def test_authenticate_api_key_wrong_secret(
    fake_token_repo: SharedTestApiTokenRepository,
) -> None:
    client_id = "test_client_id"
    token = f"{M2M_API_KEY_PREFIX}{client_id}.wrong_secret"
    token_id = generate_id(DomainIdPrefix.TOKEN)
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    secret_hash = hashlib.sha256(b"correct_secret").hexdigest()

    fake_token_repo.tokens_by_client_id[client_id] = ApiToken(
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
async def test_authenticate_api_key_rejects_expired_token_even_if_repo_returns_row() -> None:
    class UnfilteredTokenRepo(DummyApiTokenRepository):
        def __init__(self, record: ApiToken) -> None:
            self.record = record

        async def get_by_client_id(self, client_id: str) -> ApiToken | None:
            return self.record if client_id == self.record.client_id else None

    now = datetime.now(UTC)
    client_id = "expired_db_client"
    raw_secret = secrets.token_hex(16)
    token = f"{M2M_API_KEY_PREFIX}{client_id}.{raw_secret}"
    tenant_id = generate_id(DomainIdPrefix.TENANT)
    token_id = generate_id(DomainIdPrefix.TOKEN)
    secret_hash = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()
    expires_at = now + timedelta(minutes=5)

    repo = UnfilteredTokenRepo(
        ApiToken(
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
    )

    valid_identity = await authenticate_api_key(
        token, repo, now=now + timedelta(minutes=4, seconds=59)
    )
    assert valid_identity.tenant_id == tenant_id

    with pytest.raises(AuthenticationError) as exc:
        await authenticate_api_key(token, repo, now=expires_at)
    assert str(exc.value) == "APIKEY_INVALID_OR_REVOKED"


@pytest.mark.asyncio
async def test_revoke_and_delete_use_cases_enforce_shared_state_across_instances() -> None:
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
        expires_at=None,
        now=now,
    ).unwrap()
    await uow.api_token_repo.save(seeded)

    identity = await authenticate_api_key(raw_key, uow.api_token_repo, now=now)
    assert identity.tenant_id == tenant_id

    revoke_uc = UpdateApiTokenUseCase(uow=uow)
    assert (
        await revoke_uc.execute(
            token_id=seeded.id,
            tenant_id=tenant_id,
            command=UpdateApiTokenCommand(active=False),
        )
    ).is_ok

    with pytest.raises(AuthenticationError) as exc_revoked:
        await authenticate_api_key(raw_key, uow.api_token_repo, now=now)
    assert str(exc_revoked.value) == "APIKEY_INVALID_OR_REVOKED"

    assert (
        await revoke_uc.execute(
            token_id=seeded.id,
            tenant_id=tenant_id,
            command=UpdateApiTokenCommand(active=True),
        )
    ).is_ok
    reactivated_identity = await authenticate_api_key(raw_key, uow.api_token_repo, now=now)
    assert reactivated_identity.tenant_id == tenant_id

    delete_uc = DeleteApiTokenUseCase(uow=uow)
    assert (await delete_uc.execute(token_id=seeded.id, tenant_id=tenant_id)).is_ok

    with pytest.raises(AuthenticationError) as exc_deleted:
        await authenticate_api_key(raw_key, uow.api_token_repo, now=now)
    assert str(exc_deleted.value) == "APIKEY_INVALID_OR_REVOKED"
