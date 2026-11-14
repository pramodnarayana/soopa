"""Use case for pulling slices of deterministic synthetic records from a Simulator entity stream."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from ip.engine.domain.exceptions import IpError, IpErrorCode, Result
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort
from ip.solutions.connectors.sandbox.universal.dto import entity_dto_to_stream_spec
from ip.solutions.connectors.sandbox.universal.extraction import PullQueryEngine
from ip.solutions.connectors.sandbox.universal.inference import (
    parse_simulator_connection_config,
)
from ip.solutions.connectors.sandbox.universal.ports import SimulatorEntityReaderPort
from ip.solutions.connectors.sandbox.universal.strategies import (
    ExtractionQuery,
    PaginatedSliceDTO,
)
from ip.solutions.connectors.sandbox.universal.use_cases.connection_guard import (
    verify_simulator_connection,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class PullSimulatorRecordsCommand:
    """Command encapsulating context and extraction parameters for a simulated stream pull."""

    tenant_id: str
    connection_id: str
    stream_name: str
    query: ExtractionQuery


class PullSimulatorRecordsUseCase:
    """Authenticates the Simulator connection, resolves the entity schema, and executes the extraction strategy."""

    def __init__(
        self,
        *,
        cp_uow: IpControlPlaneUnitOfWorkPort,
        entity_reader: SimulatorEntityReaderPort,
        query_engine: PullQueryEngine | None = None,
    ) -> None:
        self._cp_uow = cp_uow
        self._entity_reader = entity_reader
        self._query_engine = query_engine or PullQueryEngine()

    async def execute(
        self, command: PullSimulatorRecordsCommand
    ) -> Result[PaginatedSliceDTO, IpError]:
        conn_res = await verify_simulator_connection(
            self._cp_uow.connections,
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
        )
        if conn_res.is_err:
            return Result.fail(conn_res.unwrap_err())

        connection = conn_res.unwrap()
        cfg = parse_simulator_connection_config(connection.public_config)

        entity_res = await self._entity_reader.get_entity_by_name(
            command.tenant_id, command.connection_id, command.stream_name
        )
        if entity_res.is_err:
            return Result.fail(entity_res.unwrap_err())

        entity = entity_res.value
        if entity is None:
            return Result.fail(
                IpError(
                    code=IpErrorCode.STREAM_NOT_FOUND,
                    message=(
                        f"Stream '{command.stream_name}' is not configured in "
                        f"Simulator connection '{command.connection_id}'."
                    ),
                    http_status=404,
                    details={
                        "connection_id": command.connection_id,
                        "stream_name": command.stream_name,
                    },
                )
            )

        spec = entity_dto_to_stream_spec(entity)
        slice_res = self._query_engine.execute(spec, seed=cfg.seed, query=command.query)

        if slice_res.is_ok:
            slice_dto = slice_res.unwrap()
            logger.info(
                "simulator_records_pulled",
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream_name=command.stream_name,
                mode=command.query.mode.value,
                count=len(slice_dto.records),
                has_more=slice_dto.has_more,
            )

        return slice_res


__all__ = ["PullSimulatorRecordsCommand", "PullSimulatorRecordsUseCase"]
