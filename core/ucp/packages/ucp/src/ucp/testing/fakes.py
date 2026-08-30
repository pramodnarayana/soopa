from collections.abc import Sequence
from typing import Any, Self

from identity.domain.models.api_token import ApiTokenDomainModel
from identity.domain.models.authorization import Role
from identity.domain.models.user import User
from identity.ports.outbound.api_token_repository_port import ApiTokenRepositoryPort
from identity.ports.outbound.role_repository_port import RoleRepositoryPort
from identity.ports.outbound.user_repository_port import UserRepositoryPort

from ucp.domain.models.tenant import Tenant
from ucp.ports.outbound.app_repository_port import AppRepositoryPort
from ucp.ports.outbound.idempotency_repository_port import IdempotencyRepositoryPort
from ucp.ports.outbound.tenant_repository_port import TenantRepositoryPort
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort
from ucp.ports.outbound.webhook_repository_port import WebhookRepositoryPort


class FakeTenantRepository(TenantRepositoryPort):
    def __init__(self) -> None:
        self.tenants: list[Tenant] = []
        self.saved_tenants: list[Tenant] = []

    async def save(self, tenant: Tenant, idempotency_key: str | None = None) -> None:
        self.saved_tenants.append(tenant)
        self.tenants = [t for t in self.tenants if t.id != tenant.id]
        self.tenants.append(tenant)

    async def find_by_id(self, id: str) -> Tenant | None:
        return next((t for t in self.tenants if t.id == id), None)

    async def find_by_idp_tenant_id(self, idp_tenant_id: str) -> Tenant | None:
        return next((t for t in self.tenants if t.idp_tenant_id == idp_tenant_id), None)

    async def find_all(self) -> list[Tenant]:
        return self.tenants

    async def delete(self, tenant: Tenant, idempotency_key: str | None = None) -> None:
        self.tenants = [t for t in self.tenants if t.id != tenant.id]

    async def soft_delete_tenant_infrastructure(self, tenant_id: str) -> None:
        pass

    async def allocate_shard(self, tenant_id: str, app_id: str, shard_id: str) -> None:
        pass

    async def upsert_app_subscription(self, tenant_id: str, app_id: str, status: str) -> None:
        pass


class FakeUserRepository(UserRepositoryPort):
    def __init__(self) -> None:
        self.users: list[User] = []
        self.tenant_memberships: set[tuple[str, str]] = set()

    async def find_users_by_tenant(self, tenant_id: str) -> list[User]:
        return [user for user in self.users if (tenant_id, user.id) in self.tenant_memberships]

    async def has_any_tenant_memberships(self, user_id: str) -> bool:
        return False

    async def find_by_email(self, email: str) -> User | None:
        return next((u for u in self.users if u.email == email), None)

    async def find_by_id(self, user_id: str) -> User | None:
        return next((u for u in self.users if u.id == user_id), None)

    async def find_by_idp_user_id(self, idp_user_id: str) -> User | None:
        return next((u for u in self.users if u.idp_user_id == idp_user_id), None)

    async def find_by_id_and_tenant(self, user_id: str, tenant_id: str) -> User | None:
        return next((u for u in self.users if u.id == user_id), None)

    async def delete(self, user: User) -> None:
        self.users = [u for u in self.users if u.id != user.id]

    async def save(self, user: User) -> None:
        self.users = [u for u in self.users if u.id != user.id]
        self.users.append(user)


class FakeRoleRepository(RoleRepositoryPort):
    def __init__(self) -> None:
        self.roles: list[Role] = []
        self.user_roles: list[tuple[str | None, str, str]] = []

    async def get_user_capabilities(self, tenant_id: str | None, user_id: str) -> set[str]:
        return set()

    async def get_by_id(self, role_id: str) -> Role | None:
        return next((r for r in self.roles if r.id == role_id), None)

    async def get_global_role_by_name(self, name: str) -> Role | None:
        return next((r for r in self.roles if r.name == name and r.tenant_id is None), None)

    async def get_global_roles(self) -> list[Role]:
        return [r for r in self.roles if r.tenant_id is None]

    async def save(self, role: Role) -> None:
        self.roles = [r for r in self.roles if r.id != role.id]
        self.roles.append(role)

    async def assign_user_role(self, tenant_id: str | None, user_id: str, role_id: str) -> None:
        self.user_roles.append((tenant_id, user_id, role_id))

    async def remove_user_roles(self, tenant_id: str | None, user_id: str) -> None:
        self.user_roles = [
            r for r in self.user_roles if not (r[0] == tenant_id and r[1] == user_id)
        ]

    async def has_any_tenant_memberships(self, user_id: str) -> bool:
        return any(r[1] == user_id for r in self.user_roles)


class DummyApiTokenRepository(ApiTokenRepositoryPort):
    async def get_all_by_tenant(self, tenant_id: str) -> list[ApiTokenDomainModel]:
        return []

    async def get_by_id(self, token_id: str, tenant_id: str) -> ApiTokenDomainModel | None:
        return None

    async def create(self, token: ApiTokenDomainModel) -> ApiTokenDomainModel:
        return token

    async def update(
        self, token_id: str, tenant_id: str, **kwargs: Any
    ) -> ApiTokenDomainModel | None:
        return None

    async def delete(self, token_id: str, tenant_id: str) -> bool:
        return True

    async def get_by_client_id(self, client_id: str) -> ApiTokenDomainModel | None:
        return None


class DummyAppRepository(AppRepositoryPort):
    async def find_all(self) -> list[Any]:
        return []

    async def find_by_id(self, app_id: str) -> Any | None:
        return None


class DummyWebhookRepository(WebhookRepositoryPort):
    async def list_webhooks(self, tenant_id: str) -> Sequence[Any]:
        return []

    async def get_webhooks_by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, str]:
        return {}

    async def find_by_id(self, tenant_id: str, webhook_id: str) -> Any | None:
        return None

    async def save(self, webhook: Any, idempotency_key: str | None = None) -> None:
        pass

    async def delete_webhook(
        self, webhook: Any, deleted_by: str, idempotency_key: str | None = None
    ) -> None:
        pass


class DummyIdempotencyRepository(IdempotencyRepositoryPort):
    async def get_result(
        self, tenant_id: str, idempotency_key: str
    ) -> tuple[bool, dict[str, Any] | None, int | None]:
        return False, None, None

    async def save_result(
        self,
        tenant_id: str,
        idempotency_key: str,
        response_body: dict[str, Any],
        response_status_code: int,
    ) -> None:
        pass


class FakeUcpUnitOfWork(UcpUnitOfWorkPort):
    def __init__(self) -> None:
        self.tenant_repo = FakeTenantRepository()
        self.user_repo = FakeUserRepository()
        self.role_repo = FakeRoleRepository()
        self.api_token_repo = DummyApiTokenRepository()
        self.app_repo = DummyAppRepository()
        self.webhook_repo = DummyWebhookRepository()
        self.idempotency_repo = DummyIdempotencyRepository()
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            self.rolled_back = True

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True
