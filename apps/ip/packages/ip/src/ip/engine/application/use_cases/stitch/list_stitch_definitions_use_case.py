"""Use case for listing all registered Stitch WorkflowDefinition DAGs."""

from __future__ import annotations

import structlog
from orchestration.ports.inbound.step_handler_port import WorkflowDefinitionRegistryPort

from ip.engine.application.use_cases.stitch.dtos import (
    StitchDefinitionSummaryDTO,
    to_definition_dto,
)

logger = structlog.get_logger(__name__)


class ListStitchDefinitionsUseCase:
    """Lists all registered Stitch WorkflowDefinition DAGs."""

    def __init__(self, *, definition_registry: WorkflowDefinitionRegistryPort) -> None:
        self._definition_registry = definition_registry

    def execute(self) -> tuple[StitchDefinitionSummaryDTO, ...]:
        defns = self._definition_registry.list_definitions()
        dtos = [to_definition_dto(d) for d in defns]
        dtos.sort(key=lambda d: (d.workflow_id, d.version))
        logger.info("list_stitch_definitions.completed", count=len(dtos))
        return tuple(dtos)


__all__ = ["ListStitchDefinitionsUseCase"]
