"""Dry-run preview use case for evaluating an L3 transformer and optional shadow version against a sample payload."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import structlog
from seedwork.domain.types import JsonDict
from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id

from ip.engine.domain.exceptions import IpError, Result, TransformerNotFoundError
from ip.engine.domain.normalization import (
    CanonicalDraft,
    EntityShadowDiff,
    FieldShadowDiff,
    ReplicaSnapshot,
    SourceReference,
    TransformationContext,
)
from ip.engine.ports.outbound.transformer_port import TransformerRegistryPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class PreviewStreamTransformationCommand:
    """Command to dry-run a pure L3 transformer (and optional shadow version) on a sample replica payload."""

    tenant_id: str
    connection_id: str
    stream: str
    transformation_id: str
    transformation_version: int
    record_key: str
    sample_payload: JsonDict
    shadow_transformation_version: int | None = None


@dataclass(frozen=True)
class PreviewDraftDTO:
    """Serialized canonical draft produced during dry-run preview."""

    canonical_type: str
    source_id: str
    fields: JsonDict
    extensions: JsonDict
    references: tuple[SourceReference, ...]


@dataclass(frozen=True)
class PreviewRejectionDTO:
    """Serialized transformation rejection produced during dry-run preview."""

    reason: str
    field_path: str | None
    detail: str


@dataclass(frozen=True)
class PreviewStreamTransformationResultDTO:
    """Result of dry-running an L3 transformer against a sample replica payload."""

    transformation_id: str
    transformation_version: int
    drafts: tuple[PreviewDraftDTO, ...]
    rejections: tuple[PreviewRejectionDTO, ...]
    shadow_transformation_version: int | None = None
    shadow_diffs: Mapping[str, EntityShadowDiff] = field(default_factory=dict)


def _compute_preview_shadow_diffs(
    active_drafts: tuple[CanonicalDraft, ...],
    shadow_drafts: tuple[CanonicalDraft, ...],
) -> dict[str, EntityShadowDiff]:
    active_by_key = {f"{d.canonical_type}:{d.source_id}": d.fields for d in active_drafts}
    shadow_by_key = {f"{d.canonical_type}:{d.source_id}": d.fields for d in shadow_drafts}
    all_keys = sorted(set(active_by_key.keys()) | set(shadow_by_key.keys()))

    diffs: dict[str, EntityShadowDiff] = {}
    for entity_key in all_keys:
        a_fields = active_by_key.get(entity_key, {})
        s_fields = shadow_by_key.get(entity_key, {})
        if a_fields != s_fields:
            field_keys = sorted(set(a_fields.keys()) | set(s_fields.keys()))
            field_diffs = tuple(
                FieldShadowDiff(
                    field_name=k,
                    active_value=a_fields.get(k),
                    shadow_value=s_fields.get(k),
                )
                for k in field_keys
                if a_fields.get(k) != s_fields.get(k)
            )
            canonical_type, _, source_id = entity_key.partition(":")
            entity_diff = EntityShadowDiff(
                canonical_type=canonical_type,
                source_id=source_id,
                field_diffs=field_diffs,
            )
            diffs[entity_diff.entity_key] = entity_diff
    return diffs


class PreviewStreamTransformationUseCase:
    """Executes a pure dry-run of an L3 transformer (and optional shadow version) without database mutations."""

    def __init__(self, *, transformer_registry: TransformerRegistryPort) -> None:
        self._transformer_registry = transformer_registry

    def execute(
        self, command: PreviewStreamTransformationCommand
    ) -> Result[PreviewStreamTransformationResultDTO, IpError]:
        bound = logger.bind(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream,
            transformation_id=command.transformation_id,
            transformation_version=command.transformation_version,
            shadow_transformation_version=command.shadow_transformation_version,
        )
        bound.info("preview_stream_transformation.received")

        active_transformer = self._transformer_registry.get(
            command.transformation_id, command.transformation_version
        )
        if active_transformer is None:
            bound.error("preview_stream_transformation.transformer_not_found")
            return Result.err(
                TransformerNotFoundError.for_version(
                    command.transformation_id, command.transformation_version
                )
            )

        shadow_transformer = None
        if command.shadow_transformation_version is not None:
            shadow_transformer = self._transformer_registry.get(
                command.transformation_id, command.shadow_transformation_version
            )
            if shadow_transformer is None:
                bound.error(
                    "preview_stream_transformation.shadow_transformer_not_found",
                    shadow_version=command.shadow_transformation_version,
                )
                return Result.err(
                    TransformerNotFoundError.for_version(
                        command.transformation_id, command.shadow_transformation_version
                    )
                )

        trace_id = generate_id(DomainIdPrefix.IP_TRACE.value)
        snapshot = ReplicaSnapshot(
            id=generate_id(DomainIdPrefix.IP_REPLICA.value),
            connection_id=command.connection_id,
            stream=command.stream,
            record_key=command.record_key,
            version=1,
            data=dict(command.sample_payload),
            is_deleted=False,
        )
        ctx = TransformationContext(
            connection_id=command.connection_id,
            stream=command.stream,
            tenant_id=command.tenant_id,
            trace_id=trace_id,
        )

        active_res = active_transformer.transform(snapshot, ctx)
        draft_dtos = tuple(
            PreviewDraftDTO(
                canonical_type=d.canonical_type,
                source_id=d.source_id,
                fields=dict(d.fields),
                extensions=dict(d.extensions),
                references=tuple(d.references),
            )
            for d in active_res.drafts
        )
        rejection_dtos = tuple(
            PreviewRejectionDTO(
                reason=str(r.reason),
                field_path=r.field_path,
                detail=r.detail,
            )
            for r in active_res.rejections
        )

        shadow_diffs: dict[str, EntityShadowDiff] = {}
        if shadow_transformer is not None:
            shadow_res = shadow_transformer.transform(snapshot, ctx)
            shadow_diffs = _compute_preview_shadow_diffs(active_res.drafts, shadow_res.drafts)

        bound.info(
            "preview_stream_transformation.completed",
            drafts_count=len(draft_dtos),
            rejections_count=len(rejection_dtos),
            shadow_diff_entities=len(shadow_diffs),
        )
        return Result.ok(
            PreviewStreamTransformationResultDTO(
                transformation_id=command.transformation_id,
                transformation_version=command.transformation_version,
                drafts=draft_dtos,
                rejections=rejection_dtos,
                shadow_transformation_version=command.shadow_transformation_version,
                shadow_diffs=shadow_diffs,
            )
        )


__all__ = [
    "PreviewDraftDTO",
    "PreviewRejectionDTO",
    "PreviewStreamTransformationCommand",
    "PreviewStreamTransformationResultDTO",
    "PreviewStreamTransformationUseCase",
]
