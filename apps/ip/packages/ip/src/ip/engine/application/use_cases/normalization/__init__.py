"""Normalization use cases package."""

from ip.engine.application.use_cases.normalization.bind_stream_mapping_use_case import (
    BindStreamMappingCommand,
    BindStreamMappingResultDTO,
    BindStreamMappingUseCase,
)
from ip.engine.application.use_cases.normalization.normalize_replica_record_use_case import (
    NormalizeReplicaRecordCommand,
    NormalizeReplicaRecordResultDTO,
    NormalizeReplicaRecordUseCase,
)
from ip.engine.application.use_cases.normalization.promote_mapping_version_use_case import (
    PromoteMappingVersionCommand,
    PromoteMappingVersionResultDTO,
    PromoteMappingVersionUseCase,
)

__all__ = [
    "BindStreamMappingCommand",
    "BindStreamMappingResultDTO",
    "BindStreamMappingUseCase",
    "NormalizeReplicaRecordCommand",
    "NormalizeReplicaRecordResultDTO",
    "NormalizeReplicaRecordUseCase",
    "PromoteMappingVersionCommand",
    "PromoteMappingVersionResultDTO",
    "PromoteMappingVersionUseCase",
]
