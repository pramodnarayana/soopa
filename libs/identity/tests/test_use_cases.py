import pytest
from identity.application.use_cases import ResolveTenantUseCase


class FakeIdentityRepository:
    def __init__(self) -> None:
        self.users: dict[int, str] = {}
        self.tenant_map: dict[int, int] = {}
        self.next_tenant_id = 1
        self.next_user_id = 1

    async def get_user_id_by_email(self, email: str) -> int | None:
        for uid, uemail in self.users.items():
            if uemail == email:
                return uid
        return None

    async def get_tenant_id_for_user(self, user_id: int) -> int | None:
        return self.tenant_map.get(user_id)

    async def provision_tenant_for_user(self, email: str, name: str) -> int:
        uid = self.next_user_id
        self.next_user_id += 1
        self.users[uid] = email

        tid = self.next_tenant_id
        self.next_tenant_id += 1

        self.tenant_map[uid] = tid
        return tid


@pytest.mark.asyncio
async def test_resolve_tenant_use_case_existing_user() -> None:
    repo = FakeIdentityRepository()
    repo.users[1] = "test@example.com"
    repo.tenant_map[1] = 100

    use_case = ResolveTenantUseCase(repo)
    tenant_id = await use_case.execute("test@example.com", "Test User")

    assert tenant_id == 100


@pytest.mark.asyncio
async def test_resolve_tenant_use_case_jit_provision() -> None:
    repo = FakeIdentityRepository()
    use_case = ResolveTenantUseCase(repo)

    tenant_id = await use_case.execute("new@example.com", "New User")
    assert tenant_id == 1
    assert repo.users[1] == "new@example.com"
    assert repo.tenant_map[1] == 1


@pytest.mark.asyncio
async def test_resolve_tenant_use_case_missing_tenant_mapping() -> None:
    repo = FakeIdentityRepository()
    repo.users[1] = "test@example.com"
    # No tenant mapping

    use_case = ResolveTenantUseCase(repo)
    with pytest.raises(ValueError, match="is not mapped to any tenant"):
        await use_case.execute("test@example.com", "Test User")
