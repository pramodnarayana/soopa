"""Pydantic HTTP request and response DTOs for declarative Field Mapping Specs."""

from __future__ import annotations

from pydantic import BaseModel, Field
from seedwork.domain.types import JsonPrimitive


class MappingRuleHttpDTO(BaseModel):
    """HTTP DTO representing a single field mapping rule."""

    target_field: str = Field(..., min_length=1)
    rule_type: str = Field(default="DIRECT")
    source_field: str | None = None
    constant_value: JsonPrimitive = None
    expression: str | None = None


class SaveMappingSpecHttpRequest(BaseModel):
    """HTTP request DTO to create or version a MappingSpec."""

    mapping_spec_id: str | None = None
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="")
    source_type: str = Field(..., min_length=1)
    target_connection_id: str = Field(..., min_length=1)
    target_entity_name: str = Field(..., min_length=1)
    rules: list[MappingRuleHttpDTO] = Field(default_factory=list)
    is_active: bool = True


class MappingSpecHttpResponse(BaseModel):
    """HTTP response DTO representing a saved MappingSpec."""

    id: str
    tenant_id: str
    name: str
    description: str
    source_type: str
    target_connection_id: str
    target_entity_name: str
    version: int
    rules: list[MappingRuleHttpDTO] = Field(default_factory=list)
    is_active: bool


__all__ = [
    "MappingRuleHttpDTO",
    "MappingSpecHttpResponse",
    "SaveMappingSpecHttpRequest",
]
