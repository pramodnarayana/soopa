import contextlib
from types import TracebackType
from typing import Protocol

from edi.ports.outbound.data_plane_outbox_repository_port import DataPlaneOutboxRepositoryPort

from as2_server.ports.outbound.repository_port import EdiMessageRepositoryPort


class AS2UnitOfWorkPort(Protocol):
    """
    Unit of Work Port for the AS2 Server.
    Provides isolated transaction management for saving AS2 messages and outbox events.
    """

    message_repo: EdiMessageRepositoryPort
    outbox_repo: DataPlaneOutboxRepositoryPort

    async def __aenter__(self) -> "AS2UnitOfWorkPort": ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class AS2UnitOfWorkFactoryPort(Protocol):
    """
    Factory to dynamically resolve and create a Unit of Work for a specific tenant shard.
    """

    def create_uow(
        self, tenant_id: str, shard_key: str, shard_url: str
    ) -> contextlib.AbstractAsyncContextManager[AS2UnitOfWorkPort]: ...
