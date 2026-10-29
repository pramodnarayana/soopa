"""Pydantic HTTP request and response DTOs for Layer-3 Transformations and Preview endpoints."""

from __future__ import annotations

from ip.engine.domain.enums import TransformationMode
from pydantic import BaseModel, Field
from seedwork.domain.types import JsonDict


class RegisteredTransformerHttpResponse(BaseModel):
    """HTTP response DTO describing a registered pure L3 code transformer."""

    transformation_id: str
    transformation_version: int
    target_types: list[str] = Field(default_factory=list)


class BindStreamTransformationHttpRequest(BaseModel):
    """HTTP request DTO to configure or update an L3 transformer for a connection stream."""

    transformation_id: str = Field(..., min_length=1)
    transformation_version: int = Field(default=1, ge=1)
    mode: TransformationMode = Field(default=TransformationMode.ACTIVE)
    shadow_transformation_version: int | None = Field(default=None, ge=1)


class TransformationHttpResponse(BaseModel):
    """HTTP response DTO representing an active or shadow stream transformation."""

    id: str
    tenant_id: str
    connection_id: str
    stream: str
    transformation_id: str
    transformation_version: int
    mode: str
    shadow_transformation_version: int | None = None
    was_created: bool | None = None


class PromoteTransformationVersionHttpResponse(BaseModel):
    """HTTP response DTO returned after promoting a candidate shadow transformation version to active."""

    id: str
    connection_id: str
    stream: str
    transformation_id: str
    promoted_version: int
    previous_version: int


class PreviewStreamTransformationHttpRequest(BaseModel):
    """HTTP request DTO for dry-running an L3 transformer and optional shadow version against a sample payload."""

    connection_id: str = Field(default="preview_conn", min_length=1)
    stream: str = Field(..., min_length=1)
    transformation_id: str = Field(..., min_length=1)
    transformation_version: int = Field(default=1, ge=1)
    record_key: str = Field(default="preview_record_1", min_length=1)
    sample_payload: JsonDict
    shadow_transformation_version: int | None = Field(default=None, ge=1)


class PreviewReferenceHttpResponse(BaseModel):
    """HTTP response DTO representing a cross-entity reference in a canonical draft."""

    field_name: str
    target_canonical_type: str
    target_source_id: str


class PreviewDraftHttpResponse(BaseModel):
    """HTTP response DTO representing a canonical draft produced during a dry-run preview."""

    canonical_type: str
    source_id: str
    fields: JsonDict
    extensions: JsonDict = Field(default_factory=dict)
    references: list[PreviewReferenceHttpResponse] = Field(default_factory=list)


class PreviewRejectionHttpResponse(BaseModel):
    """HTTP response DTO representing a transformation rejection produced during a dry-run preview."""

    reason: str
    field_path: str | None = None
    detail: str


class PreviewStreamTransformationHttpResponse(BaseModel):
    """HTTP response DTO returned by the dry-run transformer preview endpoint."""

    transformation_id: str
    transformation_version: int
    drafts: list[PreviewDraftHttpResponse] = Field(default_factory=list)
    rejections: list[PreviewRejectionHttpResponse] = Field(default_factory=list)
    shadow_transformation_version: int | None = None
    shadow_diffs: dict[str, JsonDict] = Field(default_factory=dict)


__all__ = [
    "BindStreamTransformationHttpRequest",
    "PreviewDraftHttpResponse",
    "PreviewReferenceHttpResponse",
    "PreviewRejectionHttpResponse",
    "PreviewStreamTransformationHttpRequest",
    "PreviewStreamTransformationHttpResponse",
    "PromoteTransformationVersionHttpResponse",
    "RegisteredTransformerHttpResponse",
    "TransformationHttpResponse",
]
