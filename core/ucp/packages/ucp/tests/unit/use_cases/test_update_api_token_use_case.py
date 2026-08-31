import pytest
from identity.domain.constants import IdentityIdPrefix
from identity.domain.models.api_token_models import UpdateApiTokenCommand
from seedwork.utils import generate_id

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
    result = await update_api_token_use_case.execute(
        token_id=generate_id(IdentityIdPrefix.TOKEN),
        tenant_id=generate_id(IdentityIdPrefix.TENANT),
        command=command,
    )

    assert result is None
    assert fake_uow.committed is True
