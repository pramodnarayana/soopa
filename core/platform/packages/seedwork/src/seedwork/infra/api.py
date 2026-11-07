"""Standard LaunchableApiModule protocol for bounded-context API modules."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from database.router import DatabaseRouterPort
    from fastapi import FastAPI


@runtime_checkable
class LaunchableApiModule(Protocol):
    """Standard interface for bounded-context API modules mounted into the unified API shell.

    Mirrors ``LaunchableWorker`` in ``seedwork.infra.worker``. The host API shell
    discovers enabled modules dynamically and invokes ``register_routes``, ``startup``,
    and ``shutdown`` without hardcoding domain-specific branches.
    """

    @property
    def name(self) -> str:
        """Canonical bounded-context identifier (e.g. 'ip', 'edi')."""
        ...

    def register_routes(self, app: FastAPI) -> None:
        """Registers APIRouters and domain-specific exception handlers on the host FastAPI shell."""
        ...

    async def startup(self, app: FastAPI, db_router: DatabaseRouterPort) -> None:
        """Initializes module-scoped IoC containers and resources using the shared DatabaseRouter."""
        ...

    async def shutdown(self, app: FastAPI) -> None:
        """Gracefully cleans up module-scoped resources on application shutdown."""
        ...


__all__ = ["LaunchableApiModule"]
