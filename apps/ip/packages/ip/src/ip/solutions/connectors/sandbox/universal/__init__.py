"""Universal Schema-Driven Sandbox Simulator package."""

from __future__ import annotations

from ip.solutions.connectors.sandbox.universal.cadence import (
    ChaosFaultCadenceStrategy,
    ConstantPacedCadenceStrategy,
    CronBatchCadenceStrategy,
    DiurnalWaveCadenceStrategy,
    PoissonJitterCadenceStrategy,
    RandomBurstCadenceStrategy,
    ThinPushCadenceStrategy,
    resolve_push_cadence_strategy,
)
from ip.solutions.connectors.sandbox.universal.chaos import (
    SimulatedFaultType,
    SimulatorChaosPolicy,
)
from ip.solutions.connectors.sandbox.universal.connector import (
    UniversalSchemaSimulatorConnector,
)
from ip.solutions.connectors.sandbox.universal.dto import (
    SIMULATOR_ENTITY_ID_PREFIX,
    SimulatorEntityDTO,
    entity_dto_to_stream_spec,
)
from ip.solutions.connectors.sandbox.universal.extraction import (
    BoundedTimeWindowExtractionStrategy,
    DeltaCdcExtractionStrategy,
    HighWatermarkExtractionStrategy,
    OffsetLimitExtractionStrategy,
    OpaqueTokenExtractionStrategy,
    PullQueryEngine,
    RateLimited429ExtractionStrategy,
    StreamedChunkedExtractionStrategy,
)
from ip.solutions.connectors.sandbox.universal.inference import (
    ValidatedEntityBlueprint,
    build_validated_entity_blueprint,
    extract_stream_schema_dto,
    infer_json_schema_from_sample,
    parse_simulator_connection_config,
    validate_entity_name,
)
from ip.solutions.connectors.sandbox.universal.ports import (
    DuplicateSimulatorEntityError,
    SimulatorApiProviderPort,
    SimulatorEntityNotFoundError,
    SimulatorEntityQuotaExceededError,
    SimulatorEntityReaderPort,
    SimulatorRepositoryPort,
    SimulatorUnitOfWorkPort,
)
from ip.solutions.connectors.sandbox.universal.session_reader import (
    SessionScopedSimulatorEntityReader,
)
from ip.solutions.connectors.sandbox.universal.simulate_push_use_case import (
    SimulatedPushDeliveryStyle,
    SimulatePushResultDTO,
    TriggerSimulatedPushCommand,
    TriggerSimulatedPushUseCase,
)
from ip.solutions.connectors.sandbox.universal.spec import (
    MAX_SAMPLE_BLUEPRINT_BYTES,
    MAX_SIMULATOR_ENTITIES_PER_CONNECTION,
    UNIVERSAL_SIMULATOR_APP_ID,
    SimulatorConnectionConfig,
    SimulatorStreamSpec,
    SimulatorSubmissionStatus,
    SimulatorWriteFailureCategory,
    StreamVelocityMode,
)
from ip.solutions.connectors.sandbox.universal.strategies import (
    CadenceState,
    ExtractionQuery,
    PaginatedSliceDTO,
    PullExtractionMode,
    PullExtractionStrategy,
    PushCadenceMode,
    PushCadenceStrategy,
)
from ip.solutions.connectors.sandbox.universal.synthesizer import (
    JsonSchemaRecordSynthesizer,
)
from ip.solutions.connectors.sandbox.universal.use_cases import (
    CreateSimulatorEntityCommand,
    CreateSimulatorEntityUseCase,
    DeleteSimulatorEntityCommand,
    DeleteSimulatorEntityUseCase,
    ListSimulatorEntitiesQuery,
    ListSimulatorEntitiesUseCase,
    PullSimulatorRecordsCommand,
    PullSimulatorRecordsUseCase,
    UpdateSimulatorEntityCommand,
    UpdateSimulatorEntityUseCase,
)

__all__ = [
    "MAX_SAMPLE_BLUEPRINT_BYTES",
    "MAX_SIMULATOR_ENTITIES_PER_CONNECTION",
    "SIMULATOR_ENTITY_ID_PREFIX",
    "UNIVERSAL_SIMULATOR_APP_ID",
    "BoundedTimeWindowExtractionStrategy",
    "CadenceState",
    "ChaosFaultCadenceStrategy",
    "ConstantPacedCadenceStrategy",
    "CreateSimulatorEntityCommand",
    "CreateSimulatorEntityUseCase",
    "CronBatchCadenceStrategy",
    "DeleteSimulatorEntityCommand",
    "DeleteSimulatorEntityUseCase",
    "DeltaCdcExtractionStrategy",
    "DiurnalWaveCadenceStrategy",
    "DuplicateSimulatorEntityError",
    "ExtractionQuery",
    "HighWatermarkExtractionStrategy",
    "JsonSchemaRecordSynthesizer",
    "ListSimulatorEntitiesQuery",
    "ListSimulatorEntitiesUseCase",
    "OffsetLimitExtractionStrategy",
    "OpaqueTokenExtractionStrategy",
    "PaginatedSliceDTO",
    "PoissonJitterCadenceStrategy",
    "PullExtractionMode",
    "PullExtractionStrategy",
    "PullQueryEngine",
    "PullSimulatorRecordsCommand",
    "PullSimulatorRecordsUseCase",
    "PushCadenceMode",
    "PushCadenceStrategy",
    "RandomBurstCadenceStrategy",
    "RateLimited429ExtractionStrategy",
    "SessionScopedSimulatorEntityReader",
    "SimulatePushResultDTO",
    "SimulatedFaultType",
    "SimulatedPushDeliveryStyle",
    "SimulatorApiProviderPort",
    "SimulatorChaosPolicy",
    "SimulatorConnectionConfig",
    "SimulatorEntityDTO",
    "SimulatorEntityNotFoundError",
    "SimulatorEntityQuotaExceededError",
    "SimulatorEntityReaderPort",
    "SimulatorRepositoryPort",
    "SimulatorStreamSpec",
    "SimulatorSubmissionStatus",
    "SimulatorUnitOfWorkPort",
    "SimulatorWriteFailureCategory",
    "StreamVelocityMode",
    "StreamedChunkedExtractionStrategy",
    "ThinPushCadenceStrategy",
    "TriggerSimulatedPushCommand",
    "TriggerSimulatedPushUseCase",
    "UniversalSchemaSimulatorConnector",
    "UpdateSimulatorEntityCommand",
    "UpdateSimulatorEntityUseCase",
    "ValidatedEntityBlueprint",
    "build_validated_entity_blueprint",
    "entity_dto_to_stream_spec",
    "extract_stream_schema_dto",
    "infer_json_schema_from_sample",
    "parse_simulator_connection_config",
    "resolve_push_cadence_strategy",
    "validate_entity_name",
]
