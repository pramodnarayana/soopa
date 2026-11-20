"""Application Use Cases and Command/Query DTOs for declarative Field Mapping Specs."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from ip.engine.domain.enums import IpIdPrefix
from ip.engine.domain.exceptions import (
    ConnectionNotFoundError,
    InvalidConnectionConfigError,
    IpError,
    MappingSpecInUseError,
    MappingSpecNotFoundError,
    Result,
)
from ip.engine.domain.mapping.enums import MappingRuleType
from ip.engine.domain.mapping.mapping_spec import MappingRule, MappingSpec
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort
from seedwork.domain.types import JsonValue
from seedwork.utils import generate_id

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class MappingRuleDTO:
    """Pure boundary DTO representing a single field mapping rule."""

    target_field: str
    rule_type: str = MappingRuleType.DIRECT.value
    source_field: str | None = None
    constant_value: JsonValue = None
    expression: str | None = None


@dataclass(frozen=True)
class MappingSpecDTO:
    """Pure boundary DTO representing a saved MappingSpec."""

    id: str
    tenant_id: str
    name: str
    description: str
    source_type: str
    target_connection_id: str
    target_entity_name: str
    version: int
    rules: tuple[MappingRuleDTO, ...]
    is_active: bool


@dataclass(frozen=True)
class SaveMappingSpecCommand:
    """Command to create or version a MappingSpec in the Control Plane."""

    tenant_id: str
    name: str
    source_type: str
    target_connection_id: str
    target_entity_name: str
    rules: tuple[MappingRuleDTO, ...]
    description: str = ""
    mapping_spec_id: str | None = None
    is_active: bool = True


@dataclass(frozen=True)
class GetMappingSpecQuery:
    """Query to retrieve a MappingSpec by ID."""

    tenant_id: str
    mapping_spec_id: str


@dataclass(frozen=True)
class ListMappingSpecsQuery:
    """Query to list MappingSpecs for a tenant."""

    tenant_id: str
    source_type: str | None = None
    target_connection_id: str | None = None


@dataclass(frozen=True)
class DeleteMappingSpecCommand:
    """Command to delete a MappingSpec if no active stitches reference it."""

    tenant_id: str
    mapping_spec_id: str


def _to_rule_domain(dto: MappingRuleDTO) -> MappingRule:
    try:
        rule_type = MappingRuleType(dto.rule_type.upper())
    except ValueError:
        rule_type = MappingRuleType.DIRECT

    return MappingRule(
        target_field=dto.target_field.strip(),
        rule_type=rule_type,
        source_field=dto.source_field.strip() if dto.source_field else None,
        constant_value=dto.constant_value,
        expression=dto.expression.strip() if dto.expression else None,
    )


def _to_spec_dto(spec: MappingSpec) -> MappingSpecDTO:
    return MappingSpecDTO(
        id=spec.id,
        tenant_id=spec.tenant_id,
        name=spec.name,
        description=spec.description,
        source_type=spec.source_type,
        target_connection_id=spec.target_connection_id,
        target_entity_name=spec.target_entity_name,
        version=spec.version,
        rules=tuple(
            MappingRuleDTO(
                target_field=r.target_field,
                rule_type=r.rule_type.value,
                source_field=r.source_field,
                constant_value=r.constant_value,
                expression=r.expression,
            )
            for r in spec.rules
        ),
        is_active=spec.is_active,
    )


class SaveMappingSpecUseCase:
    """Creates or updates a versioned declarative Field Mapping Spec in the Control Plane."""

    def __init__(self, *, uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(self, cmd: SaveMappingSpecCommand) -> Result[MappingSpecDTO, IpError]:
        bound = logger.bind(
            tenant_id=cmd.tenant_id,
            name=cmd.name,
            source_type=cmd.source_type,
            target_connection_id=cmd.target_connection_id,
            target_entity_name=cmd.target_entity_name,
        )
        bound.info("save_mapping_spec.received")

        if not cmd.name.strip():
            return Result.err(
                InvalidConnectionConfigError(
                    field_name="name",
                    message="MappingSpec name must not be empty.",
                )
            )

        if not cmd.source_type.strip():
            return Result.err(
                InvalidConnectionConfigError(
                    field_name="source_type",
                    message="source_type must not be empty.",
                )
            )

        if not cmd.target_connection_id.strip():
            return Result.err(
                InvalidConnectionConfigError(
                    field_name="target_connection_id",
                    message="target_connection_id must not be empty.",
                )
            )

        if not cmd.target_entity_name.strip():
            return Result.err(
                InvalidConnectionConfigError(
                    field_name="target_entity_name",
                    message="target_entity_name must not be empty.",
                )
            )

        async with self._uow:
            # Check target connection existence
            conn = await self._uow.connections.get_by_id(cmd.target_connection_id)
            if conn is None or conn.tenant_id != cmd.tenant_id:
                return Result.err(ConnectionNotFoundError.for_id(cmd.target_connection_id))

            # Resolve version
            latest = await self._uow.mapping_specs.get_latest_by_target(
                tenant_id=cmd.tenant_id,
                target_connection_id=cmd.target_connection_id,
                target_entity_name=cmd.target_entity_name,
            )

            version = 1
            spec_id = cmd.mapping_spec_id
            if spec_id:
                existing = await self._uow.mapping_specs.get_by_id(
                    tenant_id=cmd.tenant_id,
                    mapping_spec_id=spec_id,
                )
                if existing:
                    version = existing.version
            elif latest is not None:
                version = latest.version + 1
                spec_id = generate_id(IpIdPrefix.MAPPING_SPEC.value)
            else:
                spec_id = generate_id(IpIdPrefix.MAPPING_SPEC.value)

            domain_rules = tuple(_to_rule_domain(r) for r in cmd.rules)

            spec = MappingSpec(
                id=spec_id,
                tenant_id=cmd.tenant_id,
                name=cmd.name.strip(),
                description=cmd.description.strip(),
                source_type=cmd.source_type.strip(),
                target_connection_id=cmd.target_connection_id.strip(),
                target_entity_name=cmd.target_entity_name.strip(),
                version=version,
                rules=domain_rules,
                is_active=cmd.is_active,
            )
            spec.record_saved()
            await self._uow.mapping_specs.save(spec)
            await self._uow.commit()

        bound.info("save_mapping_spec.completed", mapping_spec_id=spec.id, version=spec.version)
        return Result.ok(_to_spec_dto(spec))


class GetMappingSpecUseCase:
    """Retrieves a MappingSpec by ID."""

    def __init__(self, *, uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(self, query: GetMappingSpecQuery) -> Result[MappingSpecDTO, IpError]:
        async with self._uow:
            spec = await self._uow.mapping_specs.get_by_id(
                tenant_id=query.tenant_id,
                mapping_spec_id=query.mapping_spec_id,
            )
            if spec is None:
                return Result.err(MappingSpecNotFoundError.for_id(query.mapping_spec_id))
            return Result.ok(_to_spec_dto(spec))


class ListMappingSpecsUseCase:
    """Lists MappingSpecs for a tenant."""

    def __init__(self, *, uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(self, query: ListMappingSpecsQuery) -> tuple[MappingSpecDTO, ...]:
        async with self._uow:
            specs = await self._uow.mapping_specs.list_by_tenant(
                tenant_id=query.tenant_id,
                source_type=query.source_type,
                target_connection_id=query.target_connection_id,
            )
            return tuple(_to_spec_dto(s) for s in specs)


class DeleteMappingSpecUseCase:
    """Deletes a MappingSpec from the Control Plane if no active Stitches reference it."""

    def __init__(self, *, uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(self, cmd: DeleteMappingSpecCommand) -> Result[None, IpError]:
        bound = logger.bind(
            tenant_id=cmd.tenant_id,
            mapping_spec_id=cmd.mapping_spec_id,
        )
        bound.info("delete_mapping_spec.received")

        async with self._uow:
            existing = await self._uow.mapping_specs.get_by_id(
                tenant_id=cmd.tenant_id,
                mapping_spec_id=cmd.mapping_spec_id,
            )
            if existing is None:
                bound.error("delete_mapping_spec.not_found")
                return Result.err(MappingSpecNotFoundError.for_id(cmd.mapping_spec_id))

            referencing = await self._uow.stitches.list_by_mapping_spec_id(
                tenant_id=cmd.tenant_id,
                mapping_spec_id=cmd.mapping_spec_id,
            )
            active_referencing = [s.id for s in referencing if s.is_active]
            if active_referencing:
                bound.error(
                    "delete_mapping_spec.in_use",
                    referencing_stitch_ids=active_referencing,
                )
                return Result.err(
                    MappingSpecInUseError.for_stitches(cmd.mapping_spec_id, active_referencing)
                )

            existing.mark_deleted()
            await self._uow.mapping_specs.delete(
                tenant_id=cmd.tenant_id,
                mapping_spec_id=cmd.mapping_spec_id,
            )
            await self._uow.commit()

        bound.info("delete_mapping_spec.completed")
        return Result.ok(None)
