from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class SyncUser:
    id: str
    idp_user_id: str | None


@dataclass
class SyncTenant:
    id: str
    idp_tenant_id: str | None


class IdentitySyncRepositoryPort(Protocol):
    async def get_tenant(self, tenant_id: str) -> SyncTenant | None: ...

    async def get_user(self, user_id: str) -> SyncUser | None: ...

    async def get_user_for_update(self, user_id: str) -> SyncUser | None: ...

    async def update_user_idp_mapping(self, user_id: str, idp_user_id: str) -> None: ...


class IdentitySyncUnitOfWorkPort(Protocol):
    repo: IdentitySyncRepositoryPort

    async def __aenter__(self) -> "IdentitySyncUnitOfWorkPort": ...
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
