"""Session-opening `SimulatorEntityReaderPort` adapter decoupled from concrete repository implementations."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Callable, Sequence

import structlog
from database.provider import DatabaseProvider
from database.router import DatabaseRouterPort
from ip.engine.domain.exceptions import (
    InvalidConnectionConfigError,
    IpError,
    Result,
)
from ip.solutions.connectors.sandbox.universal.dto import SimulatorEntityDTO
from ip.solutions.connectors.sandbox.universal.ports import SimulatorEntityReaderPort
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class SessionScopedSimulatorEntityReader(SimulatorEntityReaderPort):
    """Session-opening `SimulatorEntityReaderPort` delegating to an injected `reader_factory`."""

    def __init__(
        self,
        *,
        reader_factory: Callable[[AsyncSession], SimulatorEntityReaderPort],
        db_router_getter: Callable[[], DatabaseRouterPort | None] | None = None,
        db_provider_getter: Callable[[], DatabaseProvider | None] | None = None,
    ) -> None:
        self._reader_factory = reader_factory
        self._db_router_getter = db_router_getter
        self._db_provider_getter = db_provider_getter

    @contextlib.asynccontextmanager
    async def _open_session(self) -> AsyncIterator[AsyncSession | None]:
        db_router = self._db_router_getter() if self._db_router_getter is not None else None
        if db_router is not None:
            async with contextlib.aclosing(db_router.get_global_session()) as sessions:
                async for session in sessions:
                    yield session
                    return
        db_provider = self._db_provider_getter() if self._db_provider_getter is not None else None
        if db_provider is not None:
            async with db_provider.session() as provider_session:
                yield provider_session
                return
        yield None

    async def list_entities_by_connection(
        self, tenant_id: str, connection_id: str
    ) -> Result[Sequence[SimulatorEntityDTO], IpError]:
        async with self._open_session() as session:
            if session is None:
                logger.error(
                    "simulator_entity_reader_session_unavailable",
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                )
                return Result.fail(
                    InvalidConnectionConfigError(
                        field_name="connection_id",
                        message="Simulator entity reader has no bound database session provider.",
                    )
                )
            return await self._reader_factory(session).list_entities_by_connection(
                tenant_id, connection_id
            )

    async def get_entity_by_name(
        self, tenant_id: str, connection_id: str, entity_name: str
    ) -> Result[SimulatorEntityDTO | None, IpError]:
        async with self._open_session() as session:
            if session is None:
                logger.error(
                    "simulator_entity_reader_session_unavailable",
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    entity_name=entity_name,
                )
                return Result.fail(
                    InvalidConnectionConfigError(
                        field_name="connection_id",
                        message="Simulator entity reader has no bound database session provider.",
                    )
                )
            return await self._reader_factory(session).get_entity_by_name(
                tenant_id, connection_id, entity_name
            )


__all__ = ["SessionScopedSimulatorEntityReader"]
