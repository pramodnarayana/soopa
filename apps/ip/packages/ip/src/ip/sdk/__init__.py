"""SOOPA Integration Platform Solution SDK (ip-sdk).

Exposes zero-dependency data contracts, typed specs, and context-injected runners
for writing 100% pure solution business logic without decorator magic.
"""

from __future__ import annotations

from orchestration.domain.definition import RetryPolicy

from ip.sdk.builder import RequestBuilder
from ip.sdk.context import (
    StitchContext,
    StitchHttpPort,
    StitchKafkaPort,
    StitchReplicaPort,
    StitchTimeSlicerPort,
    TimeSlice,
)
from ip.sdk.contracts import HttpRequestBody, RequestSpec
from ip.sdk.registry import (
    DomainFunctionDescriptor,
    DomainFunctionKind,
    DomainFunctionRegistry,
    default_registry,
)
from ip.sdk.specs import (
    ConnectorSpec,
    MutationSpec,
    StitchSpec,
    TransformerSpec,
    retry_policy,
)
from ip.sdk.transforms import map_enum, parse_iso_datetime, safe_float, safe_int


def build_json_headers(
    content_type: str = "application/json",
    accept: str = "application/json",
) -> dict[str, str]:
    """Standardized HTTP JSON headers helper."""
    return {
        "Content-Type": content_type,
        "Accept": accept,
    }


__all__ = [
    "ConnectorSpec",
    "DomainFunctionDescriptor",
    "DomainFunctionKind",
    "DomainFunctionRegistry",
    "HttpRequestBody",
    "MutationSpec",
    "RequestBuilder",
    "RequestSpec",
    "RetryPolicy",
    "StitchContext",
    "StitchHttpPort",
    "StitchKafkaPort",
    "StitchReplicaPort",
    "StitchSpec",
    "StitchTimeSlicerPort",
    "TimeSlice",
    "TransformerSpec",
    "build_json_headers",
    "default_registry",
    "map_enum",
    "parse_iso_datetime",
    "retry_policy",
    "safe_float",
    "safe_int",
]
