import pytest
from identity.domain.models.api_token_models import UpdateApiTokenCommand

from ucp.application.use_cases.api_tokens.update_api_token_use_case import UpdateApiTokenUseCase
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow():
    return FakeUcpUnitOfWork()


@pytest.fixture
def update_api_token_use_case(fake_uow):
    return UpdateApiTokenUseCase(uow=fake_uow)


@pytest.mark.asyncio
async def test_update_api_token_success(update_api_token_use_case, fake_uow):
    command = UpdateApiTokenCommand(name="New Name", active=False)
    # FakeUcpUnitOfWork returns None from DummyApiTokenRepository.update
    result = await update_api_token_use_case.execute(
        token_id="tok_123",  # noqa: S106
        tenant_id="ten_123",
        command=command,
    )

    assert result is None
    assert fake_uow.committed is True
