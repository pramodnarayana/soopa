import datetime

import pytest

from identity.domain.authentication_strategy import AuthenticationStrategyPort
from identity.domain.identity_context import IdentityContext
from identity.domain.models.api_token import ApiTokenDomainModel
from identity.domain.models.api_token_models import (
    ApiTokenCreatedResult,
    CreateApiTokenCommand,
    UpdateApiTokenCommand,
)
from identity.testing.fakes.fake_identity_uow import FakeIdentityUnitOfWork


def test_api_token_models():
    cmd = CreateApiTokenCommand(name="test")
    assert cmd.name == "test"
    assert cmd.expires_at is None

    cmd2 = UpdateApiTokenCommand(name="test2", active=True)
    assert cmd2.name == "test2"
    assert cmd2.active is True

    res = ApiTokenCreatedResult(
        id="123",
        name="test",
        client_id="client123",
        active=True,
        last_used_at=None,
        expires_at=None,
        created_at=datetime.datetime.now(),
        token="super_secret_token",
    )
    assert res.id == "123"
    assert res.token == "super_secret_token"


def test_authentication_strategy_port():
    class DummyAuthStrategy(AuthenticationStrategyPort):
        def can_handle(self, token: str) -> bool:
            return token == "test"

        async def authenticate(self, token: str) -> IdentityContext:
            return IdentityContext(is_authenticated=True)

    strategy = DummyAuthStrategy()
    assert strategy.can_handle("test")


def test_fake_identity_uow_properties():
    uow = FakeIdentityUnitOfWork()
    assert uow.role_repo is not None
    assert uow.user_repo is not None
    assert uow.api_token_repo is not None
    assert uow.committed is False
    assert uow.rolled_back is False


@pytest.mark.asyncio
async def test_fake_identity_uow_commit_rollback():
    uow = FakeIdentityUnitOfWork()
    async with uow:
        pass
    assert uow.committed is True

    uow2 = FakeIdentityUnitOfWork()
    with pytest.raises(ValueError):
        async with uow2:
            raise ValueError("Test")
    assert uow2.rolled_back is True


@pytest.mark.asyncio
async def test_fake_api_token_repo():
    uow = FakeIdentityUnitOfWork()

    token = ApiTokenDomainModel(
        id="123",
        name="test",
        tenant_id="tenant_1",
        client_id="client_1",
        active=True,
        secret_hash="hash",
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
        last_used_at=None,
        expires_at=None,
    )
    await uow.api_token_repo.create(token)

    found = await uow.api_token_repo.get_by_id("123", "tenant_1")
    assert found is not None
    assert found.name == "test"

    found_client = await uow.api_token_repo.get_by_client_id("client_1")
    assert found_client is not None
    assert found_client.id == "123"

    all_tokens = await uow.api_token_repo.get_all_by_tenant("tenant_1")
    assert len(all_tokens) == 1

    await uow.api_token_repo.delete("123", "tenant_1")
    assert await uow.api_token_repo.get_by_id("123", "tenant_1") is None


@pytest.mark.asyncio
async def test_fake_token_verifier():
    from identity.testing.fakes.fake_token_verifier import FakeTokenVerifier

    verifier = FakeTokenVerifier()

    verifier.given_valid_token("test", {"sub": "123"})
    result = await verifier.verify("test")
    assert result == {"sub": "123"}

    with pytest.raises(ValueError):
        await verifier.verify("invalid")
