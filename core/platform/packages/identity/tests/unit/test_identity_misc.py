import datetime

import pytest

from identity.domain.api_token import ApiToken
from identity.domain.authentication_strategy import AuthenticationStrategyPort
from identity.domain.identity_context import IdentityContext
from identity.ports.outbound.token_verifier_port import TokenValidationError
from identity.testing.fakes.fake_identity_uow import FakeIdentityUnitOfWork
from identity.testing.fakes.fake_token_verifier import FakeTokenVerifier


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
    now = datetime.datetime.now(datetime.UTC)

    token = ApiToken(
        id="iam_tok_123",
        name="test",
        tenant_id="iam_ten_1",
        client_id="cli_1",
        active=True,
        secret_hash="hash",
        created_at=now,
        updated_at=now,
        last_used_at=None,
        expires_at=None,
    )
    await uow.api_token_repo.save(token)

    found = await uow.api_token_repo.get_by_id("iam_tok_123", "iam_ten_1")
    assert found is not None
    assert found.name == "test"

    found_client = await uow.api_token_repo.get_by_client_id("cli_1")
    assert found_client is not None
    assert found_client.id == "iam_tok_123"

    all_tokens = await uow.api_token_repo.get_all_by_tenant("iam_ten_1")
    assert len(all_tokens) == 1

    await uow.api_token_repo.delete("iam_tok_123", "iam_ten_1")
    assert await uow.api_token_repo.get_by_id("iam_tok_123", "iam_ten_1") is None


@pytest.mark.asyncio
async def test_fake_token_verifier():

    verifier = FakeTokenVerifier()

    verifier.given_valid_token("test", {"sub": "123"})
    result = await verifier.verify("test")
    assert result == {"sub": "123"}

    with pytest.raises(TokenValidationError):
        await verifier.verify("invalid")
