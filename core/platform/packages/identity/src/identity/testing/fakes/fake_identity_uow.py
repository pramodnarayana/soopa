from types import TracebackType
from typing import Any, Self

from identity.domain.identity_context import PLATFORM_TENANT_ID
from identity.domain.models.api_token import ApiTokenDomainModel
from identity.domain.models.authorization import Role
from identity.domain.models.user import User
from identity.ports.outbound.api_token_repository_port import ApiTokenRepositoryPort
from identity.ports.outbound.role_repository_port import RoleRepositoryPort
from identity.ports.outbound.uow_port import IdentityUnitOfWorkPort
from identity.ports.outbound.user_repository_port import UserRepositoryPort


class FakeUserRepository(UserRepositoryPort):
    def __init__(self) -> None:
        self.users: list[User] = []
        self.tenant_memberships: set[tuple[str, str]] = set()

    async def find_users_by_tenant(self, tenant_id: str) -> list[User]:
        return [user for user in self.users if (tenant_id, user.id) in self.tenant_memberships]

    async def has_any_tenant_memberships(self, user_id: str) -> bool:
        return any(
            member_user_id == user_id and tenant_id != PLATFORM_TENANT_ID
            for tenant_id, member_user_id in self.tenant_memberships
        )

    async def find_by_email(self, email: str) -> User | None:
        return next((u for u in self.users if u.email == email), None)

    async def find_by_id(self, user_id: str) -> User | None:
        return next((u for u in self.users if u.id == user_id), None)

    async def find_by_idp_user_id(self, idp_user_id: str) -> User | None:
        return next((u for u in self.users if u.idp_user_id == idp_user_id), None)

    async def find_by_id_and_tenant(self, user_id: str, tenant_id: str) -> User | None:
        if (tenant_id, user_id) not in self.tenant_memberships:
            return None
        return await self.find_by_id(user_id)

    async def delete(self, user: User) -> None:
        if user in self.users:
            self.users.remove(user)

    async def save(self, user: User) -> None:
        existing = await self.find_by_id(user.id)
        if existing:
            self.users.remove(existing)
        self.users.append(user)


class FakeRoleRepository(RoleRepositoryPort):
    def __init__(self) -> None:
        self.roles: list[Role] = []
        self.user_roles: dict[tuple[str | None, str], list[str]] = {}

    async def get_user_capabilities(self, tenant_id: str | None, user_id: str) -> set[str]:
        normalized_tenant_id = PLATFORM_TENANT_ID if tenant_id is None else tenant_id
        assigned_role_ids = self.user_roles.get((normalized_tenant_id, user_id), [])
        caps = set()
        for r_id in assigned_role_ids:
            role = await self.get_by_id(r_id)
            if role:
                caps.update(role.capabilities)
        return caps

    async def get_by_id(self, role_id: str) -> Role | None:
        return next((r for r in self.roles if r.id == role_id), None)

    async def get_global_role_by_name(self, name: str) -> Role | None:
        return next((r for r in self.roles if r.tenant_id is None and r.name == name), None)

    async def get_global_roles(self) -> list[Role]:
        return [r for r in self.roles if r.tenant_id is None]

    async def save(self, role: Role) -> None:
        existing = await self.get_by_id(role.id)
        if existing:
            self.roles.remove(existing)
        self.roles.append(role)

    async def assign_user_role(self, tenant_id: str | None, user_id: str, role_id: str) -> None:
        normalized_tenant_id = PLATFORM_TENANT_ID if tenant_id is None else tenant_id
        key = (normalized_tenant_id, user_id)
        if key not in self.user_roles:
            self.user_roles[key] = []
        if role_id not in self.user_roles[key]:
            self.user_roles[key].append(role_id)

    async def remove_user_roles(self, tenant_id: str | None, user_id: str) -> None:
        normalized_tenant_id = PLATFORM_TENANT_ID if tenant_id is None else tenant_id
        key = (normalized_tenant_id, user_id)
        if key in self.user_roles:
            del self.user_roles[key]

    async def has_any_tenant_memberships(self, user_id: str) -> bool:
        return any(u_id == user_id and t_id is not None for t_id, u_id in self.user_roles)


class FakeApiTokenRepository(ApiTokenRepositoryPort):
    def __init__(self) -> None:
        self.tokens: list[ApiTokenDomainModel] = []

    async def get_all_by_tenant(self, tenant_id: str) -> list[ApiTokenDomainModel]:
        return [t for t in self.tokens if t.tenant_id == tenant_id]

    async def get_by_id(self, token_id: str, tenant_id: str) -> ApiTokenDomainModel | None:
        return next((t for t in self.tokens if t.id == token_id and t.tenant_id == tenant_id), None)

    async def create(self, token: ApiTokenDomainModel) -> ApiTokenDomainModel:
        self.tokens.append(token)
        return token

    async def update(
        self, token_id: str, tenant_id: str, **kwargs: Any
    ) -> ApiTokenDomainModel | None:
        token = await self.get_by_id(token_id, tenant_id)
        if token:
            for k, v in kwargs.items():
                setattr(token, k, v)
        return token

    async def delete(self, token_id: str, tenant_id: str) -> bool:
        token = await self.get_by_id(token_id, tenant_id)
        if token:
            self.tokens.remove(token)
            return True
        return False

    async def get_by_client_id(self, client_id: str) -> ApiTokenDomainModel | None:
        return next((t for t in self.tokens if t.client_id == client_id and t.active), None)


class FakeIdentityUnitOfWork(IdentityUnitOfWorkPort):
    def __init__(self) -> None:
        self.user_repo = FakeUserRepository()
        self.role_repo = FakeRoleRepository()
        self.api_token_repo = FakeApiTokenRepository()
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True
