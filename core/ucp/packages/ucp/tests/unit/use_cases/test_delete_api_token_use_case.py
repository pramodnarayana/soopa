import pytest

from ucp.application.use_cases.api_tokens.delete_api_token_use_case import DeleteApiTokenUseCase
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow():
    return FakeUcpUnitOfWork()


@pytest.fixture
def delete_api_token_use_case(fake_uow):
    return DeleteApiTokenUseCase(uow=fake_uow)


@pytest.mark.asyncio
async def test_delete_api_token_success(delete_api_token_use_case, fake_uow):
    result = await delete_api_token_use_case.execute(
        token_id="tok_123",  # noqa: S106
        tenant_id="ten_123",
    )
    assert result is True
    assert fake_uow.committed is True
