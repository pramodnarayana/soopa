from dataclasses import dataclass
from types import TracebackType
from typing import Protocol


@dataclass(frozen=True)
class SyncUser:
    id: str
    idp_user_id: str | None


@dataclass(frozen=True)
class SyncTenant:
    id: str
    name: str
    idp_tenant_id: str | None


class IdentitySyncRepositoryPort(Protocol):
    async def get_tenant(self, tenant_id: str) -> SyncTenant | None: ...

    async def update_tenant_idp_mapping(self, tenant_id: str, idp_tenant_id: str) -> None: ...

    async def get_user(self, user_id: str) -> SyncUser | None: ...

    async def get_user_for_update(self, user_id: str) -> SyncUser | None: ...

    async def update_user_idp_mapping(self, user_id: str, idp_user_id: str) -> None: ...


class IdentitySyncUnitOfWorkPort(Protocol):
    @property
    def repo(self) -> IdentitySyncRepositoryPort: ...

    async def __aenter__(self) -> "IdentitySyncUnitOfWorkPort": ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
