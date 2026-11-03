from collections.abc import Mapping, Sequence
from datetime import datetime
from types import TracebackType
from typing import Self

from identity.domain.api_token import ApiToken
from identity.domain.authorization import Role
from identity.domain.identity_context import PLATFORM_TENANT_ID
from identity.domain.user import User
from identity.ports.outbound.api_token_repository_port import ApiTokenRepositoryPort
from identity.ports.outbound.role_repository_port import RoleRepositoryPort
from identity.ports.outbound.user_repository_port import UserRepositoryPort
from seedwork.domain.types import JsonDict

from ucp.domain.app import App
from ucp.domain.tenant import Tenant
from ucp.domain.webhook import Webhook
from ucp.ports.outbound.app_repository_port import AppRepositoryPort
from ucp.ports.outbound.idempotency_repository_port import IdempotencyRepositoryPort
from ucp.ports.outbound.tenant_repository_port import TenantRepositoryPort
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort
from ucp.ports.outbound.webhook_repository_port import WebhookRepositoryPort


class FakeTenantRepository(TenantRepositoryPort):
    def __init__(self) -> None:
        self.tenants: list[Tenant] = []
        self.saved_tenants: list[Tenant] = []
        self.allocations: list[tuple[str, str, str]] = []
        self.subscriptions: dict[tuple[str, str], str] = {}
        self.shard_statuses: dict[tuple[str, str], str] = {}

    async def save(self, tenant: Tenant, idempotency_key: str | None = None) -> None:
        self.saved_tenants.append(tenant)
        self.tenants = [t for t in self.tenants if t.id != tenant.id]
        self.tenants.append(tenant)

    async def insert_if_slug_available(
        self, tenant: Tenant, idempotency_key: str | None = None
    ) -> bool:
        if any(t.slug == tenant.slug for t in self.tenants):
            return False
        await self.save(tenant, idempotency_key)
        return True

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
        self.allocations.append((tenant_id, app_id, shard_id))

    async def upsert_app_subscription(self, tenant_id: str, app_id: str, status: str) -> None:
        self.subscriptions[(tenant_id, app_id)] = status

    async def update_shard_status(self, tenant_id: str, app_id: str, status: str) -> None:
        self.shard_statuses[(tenant_id, app_id)] = status


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
        return next(
            (
                u
                for u in self.users
                if u.id == user_id and (tenant_id, u.id) in self.tenant_memberships
            ),
            None,
        )

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

    async def get_platform_role_by_id(self, role_id: str) -> Role | None:
        return next(
            (r for r in self.roles if r.id == role_id and r.tenant_id == PLATFORM_TENANT_ID), None
        )

    async def get_platform_role_by_name(self, name: str) -> Role | None:
        return next(
            (r for r in self.roles if r.tenant_id == PLATFORM_TENANT_ID and r.name == name), None
        )

    async def get_platform_roles(self) -> list[Role]:
        return [r for r in self.roles if r.tenant_id == PLATFORM_TENANT_ID]

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
    def __init__(self) -> None:
        self.tokens: list[ApiToken] = []

    async def get_all_by_tenant(self, tenant_id: str) -> list[ApiToken]:
        return [t for t in self.tokens if t.tenant_id == tenant_id]

    async def get_by_id(self, token_id: str, tenant_id: str) -> ApiToken | None:
        return next((t for t in self.tokens if t.id == token_id and t.tenant_id == tenant_id), None)

    async def save(self, token: ApiToken) -> ApiToken:
        existing = await self.get_by_id(token.id, token.tenant_id)
        if existing is not None:
            self.tokens.remove(existing)
        self.tokens.append(token)
        return token

    async def delete(self, token_id: str, tenant_id: str) -> bool:
        token = await self.get_by_id(token_id, tenant_id)
        if token is not None:
            self.tokens.remove(token)
            return True
        return False

    async def get_by_client_id(
        self, client_id: str, now: datetime | None = None
    ) -> ApiToken | None:
        return next(
            (
                t
                for t in self.tokens
                if t.client_id == client_id and t.active and not t.is_expired(at=now)
            ),
            None,
        )


class DummyAppRepository(AppRepositoryPort):
    def __init__(self) -> None:
        self.apps: list[App] = []

    async def find_all(self) -> list[App]:
        return self.apps

    async def find_by_id(self, app_id: str) -> App | None:
        return next((a for a in self.apps if a.id == app_id), None)


class DummyWebhookRepository(WebhookRepositoryPort):
    async def list_webhooks(self, tenant_id: str) -> Sequence[Webhook]:
        return []

    async def get_webhooks_by_ids(self, tenant_id: str, ids: Sequence[str]) -> Mapping[str, str]:
        return {}

    async def find_by_id(self, tenant_id: str, webhook_id: str) -> Webhook | None:
        return None

    async def save(self, webhook: Webhook, idempotency_key: str | None = None) -> None:
        pass

    async def delete_webhook(
        self, webhook: Webhook, deleted_by: str, idempotency_key: str | None = None
    ) -> None:
        pass


class DummyIdempotencyRepository(IdempotencyRepositoryPort):
    async def get_result(
        self, tenant_id: str, idempotency_key: str
    ) -> tuple[bool, JsonDict | None, int | None]:
        return False, None, None

    async def save_result(
        self,
        tenant_id: str,
        idempotency_key: str,
        response_body: JsonDict,
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

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self.rolled_back = True

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True
