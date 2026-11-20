"""Use case for fetching a specific Stitch WorkflowDefinition by ID."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from orchestration.ports.inbound.step_handler_port import WorkflowDefinitionRegistryPort

from ip.engine.application.use_cases.stitch.dtos import (
    StitchDefinitionSummaryDTO,
    to_definition_dto,
)
from ip.engine.domain.exceptions import (
    IpError,
    Result,
    StitchDefinitionNotFoundError,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class GetStitchDefinitionQuery:
    """Query to fetch a specific Stitch WorkflowDefinition by ID and optional version."""

    workflow_id: str
    version: int | None = None


class GetStitchDefinitionUseCase:
    """Fetches a specific Stitch WorkflowDefinition by ID (and optional version)."""

    def __init__(self, *, definition_registry: WorkflowDefinitionRegistryPort) -> None:
        self._definition_registry = definition_registry

    def execute(
        self, query: GetStitchDefinitionQuery
    ) -> Result[StitchDefinitionSummaryDTO, IpError]:
        bound = logger.bind(workflow_id=query.workflow_id, version=query.version)
        bound.info("get_stitch_definition.received")
        if query.version is not None:
            res = self._definition_registry.get(query.workflow_id, query.version)
        else:
            res = self._definition_registry.get_latest(query.workflow_id)
        if res.is_err:
            bound.error("get_stitch_definition.not_found")
            return Result.err(
                StitchDefinitionNotFoundError.for_workflow(query.workflow_id, query.version)
            )
        defn = res.unwrap()
        bound.info("get_stitch_definition.completed", resolved_version=defn.version)
        return Result.ok(to_definition_dto(defn))


__all__ = [
    "GetStitchDefinitionQuery",
    "GetStitchDefinitionUseCase",
]
