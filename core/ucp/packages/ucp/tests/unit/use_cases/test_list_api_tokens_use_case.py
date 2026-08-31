import pytest
from identity.domain.constants import IdentityIdPrefix
from seedwork.utils import generate_id

from ucp.application.use_cases.api_tokens.list_api_tokens_use_case import ListApiTokensUseCase
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow():
    return FakeUcpUnitOfWork()


@pytest.fixture
def list_api_tokens_use_case(fake_uow):
    return ListApiTokensUseCase(uow=fake_uow)


@pytest.mark.asyncio
async def test_list_api_tokens_success(list_api_tokens_use_case, fake_uow):
    result = await list_api_tokens_use_case.execute(tenant_id=generate_id(IdentityIdPrefix.TENANT))
    assert result == []
