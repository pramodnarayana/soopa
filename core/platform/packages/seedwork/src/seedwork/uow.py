"""Base Unit of Work Port Protocol for all bounded contexts."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self


class UnitOfWorkPort(Protocol):
    """Abstract base transaction boundary contract for all bounded contexts."""

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


__all__ = ["UnitOfWorkPort"]
