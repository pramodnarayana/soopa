"""Use case for registering or updating a Stitch for a tenant."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import structlog
from identity.domain.identity_context import PLATFORM_TENANT_ID
from orchestration.ports.inbound.step_handler_port import WorkflowDefinitionRegistryPort
from seedwork.domain.types import JsonPrimitive
from seedwork.utils import generate_id
from structlog.stdlib import BoundLogger as FilteringBoundLogger

from ip.engine.application.use_cases.stitch.dtos import StitchSummaryDTO, to_stitch_dto
from ip.engine.domain.enums import IpIdPrefix
from ip.engine.domain.exceptions import (
    InvalidConnectionConfigError,
    IpError,
    IpErrorCode,
    Result,
    StitchDefinitionNotFoundError,
)
from ip.engine.domain.stitch.stitch import Stitch
from ip.engine.ports.outbound.stitch_catalog_registry_port import StitchCatalogRegistryPort
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RegisterStitchCommand:
    """Command to register or update a Stitch for a tenant."""

    tenant_id: str
    canonical_event_type: str
    target_workflow_id: str
    name: str = ""
    description: str = ""
    mapping_spec_id: str | None = None
    stitch_id: str | None = None
    filter_conditions: Mapping[str, JsonPrimitive] = field(default_factory=dict)
    is_active: bool = True
    workflow_id: str | None = None  # Alias support if callers pass workflow_id
    idempotency_key_field: str = ""
    concurrency_key_field: str = ""


class RegisterStitchUseCase:
    """Validates and persists a Stitch connecting an L3 Canonical Event to an automated workflow."""

    def __init__(
        self,
        *,
        stitch_catalog: StitchCatalogRegistryPort,
        definition_registry: WorkflowDefinitionRegistryPort,
        uow: IpControlPlaneUnitOfWorkPort | None = None,
    ) -> None:
        self._stitch_catalog = stitch_catalog
        self._definition_registry = definition_registry
        self._uow = uow

    @staticmethod
    def _validate_filter_conditions(conditions: Mapping[str, object]) -> Result[None, IpError]:
        for filter_key, filter_val in conditions.items():
            if not (isinstance(filter_val, (str, int, float, bool)) or filter_val is None):
                return Result.err(
                    IpError(
                        code=IpErrorCode.INVALID_CONFIG,
                        message=(
                            f"filter_conditions value for key '{filter_key}' must be a primitive "
                            f"(str, int, float, bool, None), got {type(filter_val).__name__}"
                        ),
                        http_status=400,
                        details={"key": str(filter_key), "value_type": type(filter_val).__name__},
                    )
                )
        return Result.ok(None)

    async def _check_stitch_id_collision(
        self, stitch_id: str, tenant_id: str, bound: FilteringBoundLogger
    ) -> Result[None, IpError]:
        if self._uow is not None:
            async with self._uow:
                existing = await self._uow.stitches.get_by_id_global(stitch_id=stitch_id)
                if (
                    existing is not None
                    and existing.tenant_id != tenant_id
                    and existing.tenant_id != PLATFORM_TENANT_ID
                ):
                    bound.error(
                        "register_stitch.cross_tenant_collision",
                        existing_tenant_id=existing.tenant_id,
                    )
                    return Result.err(
                        IpError(
                            code=IpErrorCode.VALIDATION_FAILED,
                            message=f"Stitch '{stitch_id}' already exists and belongs to another tenant.",
                            http_status=409,
                            details={"stitch_id": stitch_id, "tenant_id": tenant_id},
                        )
                    )
        else:
            existing_in_mem = self._stitch_catalog.find_any_stitch_by_id(stitch_id=stitch_id)
            if (
                existing_in_mem is not None
                and existing_in_mem.tenant_id != tenant_id
                and existing_in_mem.tenant_id != PLATFORM_TENANT_ID
            ):
                bound.error(
                    "register_stitch.cross_tenant_collision",
                    existing_tenant_id=existing_in_mem.tenant_id,
                )
                return Result.err(
                    IpError(
                        code=IpErrorCode.VALIDATION_FAILED,
                        message=f"Stitch '{stitch_id}' already exists and belongs to another tenant.",
                        http_status=409,
                        details={"stitch_id": stitch_id, "tenant_id": tenant_id},
                    )
                )
        return Result.ok(None)

    async def execute(self, command: RegisterStitchCommand) -> Result[StitchSummaryDTO, IpError]:
        target_wf_id = (command.target_workflow_id or command.workflow_id or "").strip()
        bound = logger.bind(
            tenant_id=command.tenant_id,
            target_workflow_id=target_wf_id,
            canonical_event_type=command.canonical_event_type,
        )
        bound.info("register_stitch.received")

        if not command.canonical_event_type.strip():
            bound.error("register_stitch.empty_event_type")
            return Result.err(
                InvalidConnectionConfigError(
                    field_name="canonical_event_type",
                    message="canonical_event_type must not be empty.",
                )
            )

        if not target_wf_id:
            bound.error("register_stitch.empty_target_workflow_id")
            return Result.err(
                InvalidConnectionConfigError(
                    field_name="target_workflow_id",
                    message="target_workflow_id must not be empty.",
                )
            )

        defn_res = self._definition_registry.get_latest(target_wf_id)
        if defn_res.is_err:
            bound.error("register_stitch.definition_not_found")
            return Result.err(StitchDefinitionNotFoundError.for_workflow(target_wf_id, 1))

        if command.stitch_id and command.stitch_id.strip():
            stitch_id = command.stitch_id.strip()
            collision_res = await self._check_stitch_id_collision(
                stitch_id, command.tenant_id, bound
            )
            if collision_res.is_err:
                return Result.err(collision_res.unwrap_err())
        else:
            stitch_id = generate_id(IpIdPrefix.STITCH.value)

        filter_res = self._validate_filter_conditions(command.filter_conditions)
        if filter_res.is_err:
            return Result.err(filter_res.unwrap_err())

        stitch = Stitch(
            id=stitch_id,
            tenant_id=command.tenant_id,
            canonical_event_type=command.canonical_event_type.strip(),
            target_workflow_id=target_wf_id,
            name=command.name.strip(),
            description=command.description.strip(),
            mapping_spec_id=(
                command.mapping_spec_id.strip()
                if command.mapping_spec_id and command.mapping_spec_id.strip()
                else None
            ),
            filter_conditions=dict(command.filter_conditions),
            is_active=command.is_active,
            idempotency_key_field=command.idempotency_key_field,
            concurrency_key_field=command.concurrency_key_field,
        )
        stitch.record_registered()
        if self._uow is not None:
            async with self._uow:
                await self._uow.stitches.save(stitch)
                await self._uow.commit()
        self._stitch_catalog.register_stitch(stitch)
        bound.info("register_stitch.completed", stitch_id=stitch.id)
        return Result.ok(to_stitch_dto(stitch))


__all__ = [
    "RegisterStitchCommand",
    "RegisterStitchUseCase",
]
