"""First-Class Universal Schema Simulator Connector (`ConnectorPort` implementation)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Sequence
from typing import Final

import structlog
from ip.engine.adapters.outbound.connectors.base_connector import BaseConnector
from ip.engine.domain.connection.enums import (
    AuthType,
    CatalogCategory,
    ConnectorArchitectureType,
    PropertyType,
)
from ip.engine.domain.exceptions import (
    InvalidConnectionConfigError,
    IpError,
    IpErrorCode,
    Result,
)
from ip.engine.ports.outbound.catalog_registry_port import CatalogAppSummaryDTO
from ip.engine.ports.outbound.connector_port import (
    AppSpecDTO,
    ConnectionCheckResultDTO,
    ConnectorPropertyDTO,
    DiscoveredCatalogDTO,
    RecordEnvelopeDTO,
    StreamSchemaDTO,
    WriteRecordCommand,
    WriteResultDTO,
)
from ip.solutions.connectors.sandbox.universal.dto import entity_dto_to_stream_spec
from ip.solutions.connectors.sandbox.universal.inference import (
    extract_stream_schema_dto,
    parse_simulator_connection_config,
)
from ip.solutions.connectors.sandbox.universal.ports import SimulatorEntityReaderPort
from ip.solutions.connectors.sandbox.universal.spec import (
    SimulatorConnectionConfig,
    SimulatorSubmissionStatus,
    SimulatorWriteFailureCategory,
)
from ip.solutions.connectors.sandbox.universal.synthesizer import JsonSchemaRecordSynthesizer
from seedwork.domain.types import JsonDict

logger = structlog.get_logger(__name__)


class UniversalSchemaSimulatorConnector(BaseConnector):
    """Domain-agnostic JSON-Schema-driven tenant Simulator connector (`NO_AUTH`)."""

    APP_ID: Final[str] = "universal_simulator"

    def __init__(
        self,
        *,
        entity_reader: SimulatorEntityReaderPort | None = None,
        synthesizer: JsonSchemaRecordSynthesizer | None = None,
    ) -> None:
        self._entity_reader = entity_reader
        self._synthesizer = synthesizer or JsonSchemaRecordSynthesizer()

    @classmethod
    def default_catalog_summary(cls) -> CatalogAppSummaryDTO:
        return CatalogAppSummaryDTO(
            app_id=cls.APP_ID,
            display_name="Universal Schema Simulator",
            category=CatalogCategory.SANDBOX,
            auth_type=AuthType.NO_AUTH,
            description=None,
            connector_type=ConnectorArchitectureType.NATIVE_SIMULATOR,
        )

    @property
    def app_id(self) -> str:
        return self.APP_ID

    def spec(self) -> AppSpecDTO:
        """Exposes optional `seed` and `records_per_pull` parameters (`NO_AUTH`)."""
        return AppSpecDTO(
            app_id=self.APP_ID,
            display_name="Universal Schema Simulator",
            auth_type=AuthType.NO_AUTH,
            category=CatalogCategory.SANDBOX,
            description=None,
            properties=(
                ConnectorPropertyDTO(
                    name="seed",
                    label="Seed",
                    type=PropertyType.NUMBER,
                    required=False,
                    default=42,
                    description=None,
                ),
                ConnectorPropertyDTO(
                    name="records_per_pull",
                    label="Records per Pull",
                    type=PropertyType.NUMBER,
                    required=False,
                    default=25,
                    description=None,
                ),
            ),
        )

    def _resolve_connection_scope(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        public_config: JsonDict,
    ) -> Result[tuple[str, str, SimulatorConnectionConfig, SimulatorEntityReaderPort], IpError]:
        cfg = parse_simulator_connection_config(public_config)
        cleaned_tenant_id = tenant_id.strip()
        cleaned_conn_id = connection_id.strip()
        if self._entity_reader is None:
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name="connection_id",
                    message="Simulator entity reader is not initialized on UniversalSchemaSimulatorConnector.",
                )
            )
        if not cleaned_tenant_id or not cleaned_conn_id:
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name="connection_id",
                    message="Explicit tenant_id and connection_id are required for Simulator execution.",
                )
            )
        return Result.ok((cleaned_tenant_id, cleaned_conn_id, cfg, self._entity_reader))

    async def check(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> ConnectionCheckResultDTO:
        """Validates simulator parameters (`NO_AUTH` — always ready)."""
        _ = credentials
        cfg = parse_simulator_connection_config(public_config)
        logger.info(
            "universal_simulator_check_succeeded",
            app_id=self.APP_ID,
            seed=cfg.seed,
            default_records_per_pull=cfg.default_records_per_pull,
        )
        return ConnectionCheckResultDTO.ok(
            f"Universal Schema Simulator ready (seed={cfg.seed}, records_per_pull={cfg.default_records_per_pull})."
        )

    async def discover(
        self,
        connection_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
        *,
        tenant_id: str,
    ) -> DiscoveredCatalogDTO:
        """Loads `ip.simulator_entities` for `(tenant_id, connection_id)` and returns `StreamSchemaDTO`s (`streams=()` if empty)."""
        _ = credentials
        scope_res = self._resolve_connection_scope(
            tenant_id=tenant_id,
            connection_id=connection_id,
            public_config=public_config,
        )
        if scope_res.is_err:
            err = scope_res.unwrap_err()
            logger.error(
                "universal_simulator_discover_scope_invalid",
                tenant_id=tenant_id,
                connection_id=connection_id,
                error_code=err.code.value,
                reason=err.message,
            )
            return DiscoveredCatalogDTO.from_error(connection_id, err)

        cleaned_tenant_id, cleaned_conn_id, _, reader = scope_res.unwrap()
        entities = await reader.list_entities_by_connection(cleaned_tenant_id, cleaned_conn_id)
        streams: list[StreamSchemaDTO] = [
            extract_stream_schema_dto(entity_dto_to_stream_spec(entity)) for entity in entities
        ]
        logger.info(
            "universal_simulator_discover_completed",
            tenant_id=cleaned_tenant_id,
            connection_id=cleaned_conn_id,
            discovered_stream_count=len(streams),
            streams=[s.name for s in streams],
        )
        return self.build_catalog_dto(connection_id=cleaned_conn_id, streams=tuple(streams))

    async def list_objects(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        limit: int = 100,
        cursor: str | None = None,
        *,
        tenant_id: str,
        connection_id: str,
    ) -> Sequence[str]:
        """Lists synthetic object IDs for `stream_name` in `(tenant_id, connection_id)`."""
        _ = credentials
        self._last_error = None
        scope_res = self._resolve_connection_scope(
            tenant_id=tenant_id,
            connection_id=connection_id,
            public_config=public_config,
        )
        if scope_res.is_err:
            err = scope_res.unwrap_err()
            self._last_error = err
            logger.error(
                "universal_simulator_list_objects_scope_invalid",
                stream_name=stream_name,
                error_code=err.code.value,
                reason=err.message,
            )
            return ()
        cleaned_tenant_id, cleaned_conn_id, cfg, reader = scope_res.unwrap()
        entity = await reader.get_entity_by_name(cleaned_tenant_id, cleaned_conn_id, stream_name)
        if entity is None:
            logger.error(
                "universal_simulator_list_objects_stream_not_found",
                tenant_id=cleaned_tenant_id,
                connection_id=cleaned_conn_id,
                stream_name=stream_name,
            )
            return ()
        spec = entity_dto_to_stream_spec(entity)
        batch = self._synthesizer.synthesize_batch(
            spec,
            seed=cfg.seed,
            cursor=cursor,
            limit=min(max(1, limit), spec.records_per_pull),
        )
        object_ids = tuple(env.record_id for env in batch)
        logger.info(
            "universal_simulator_list_objects_completed",
            tenant_id=cleaned_tenant_id,
            connection_id=cleaned_conn_id,
            stream_name=stream_name,
            object_count=len(object_ids),
        )
        return object_ids

    async def read_stream(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        cursor: str | None = None,
        limit: int = 100,
        *,
        tenant_id: str,
        connection_id: str,
    ) -> AsyncIterator[RecordEnvelopeDTO]:
        """Pull Mode: Synthesizes deterministic records newer than `cursor` for `(tenant_id, connection_id)`."""
        _ = credentials
        self._last_error = None
        scope_res = self._resolve_connection_scope(
            tenant_id=tenant_id,
            connection_id=connection_id,
            public_config=public_config,
        )
        if scope_res.is_err:
            err = scope_res.unwrap_err()
            self._last_error = err
            logger.error(
                "universal_simulator_read_stream_scope_invalid",
                stream_name=stream_name,
                error_code=err.code.value,
                reason=err.message,
            )
            return

        cleaned_tenant_id, cleaned_conn_id, cfg, reader = scope_res.unwrap()
        entity = await reader.get_entity_by_name(cleaned_tenant_id, cleaned_conn_id, stream_name)
        if entity is None:
            not_found_err = IpError(
                code=IpErrorCode.STREAM_NOT_FOUND,
                message=f"Entity '{stream_name}' is not configured in Simulator connection '{cleaned_conn_id}'.",
                http_status=404,
            )
            self._last_error = not_found_err
            logger.error(
                "universal_simulator_read_stream_not_found",
                tenant_id=cleaned_tenant_id,
                connection_id=cleaned_conn_id,
                stream_name=stream_name,
            )
            return

        spec = entity_dto_to_stream_spec(entity)
        effective_limit = min(max(1, limit), spec.records_per_pull)
        batch = self._synthesizer.synthesize_batch(
            spec,
            seed=cfg.seed,
            cursor=cursor,
            limit=effective_limit,
        )
        logger.info(
            "universal_simulator_read_stream_completed",
            tenant_id=cleaned_tenant_id,
            connection_id=cleaned_conn_id,
            stream_name=stream_name,
            cursor=cursor,
            emitted_count=len(batch),
        )
        for env in batch:
            yield env

    async def fetch_record(
        self,
        stream_name: str,
        record_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
        *,
        tenant_id: str,
        connection_id: str,
    ) -> RecordEnvelopeDTO | None:
        """Thin-Push Fetch Mode: Reconstructs `record_id` for `(tenant_id, connection_id)`."""
        _ = credentials
        self._last_error = None
        scope_res = self._resolve_connection_scope(
            tenant_id=tenant_id,
            connection_id=connection_id,
            public_config=public_config,
        )
        if scope_res.is_err:
            err = scope_res.unwrap_err()
            self._last_error = err
            logger.error(
                "universal_simulator_fetch_record_scope_invalid",
                stream_name=stream_name,
                record_id=record_id,
                error_code=err.code.value,
                reason=err.message,
            )
            return None
        cleaned_tenant_id, cleaned_conn_id, cfg, reader = scope_res.unwrap()
        entity = await reader.get_entity_by_name(cleaned_tenant_id, cleaned_conn_id, stream_name)
        if entity is None:
            logger.error(
                "universal_simulator_fetch_record_stream_not_found",
                tenant_id=cleaned_tenant_id,
                connection_id=cleaned_conn_id,
                stream_name=stream_name,
                record_id=record_id,
            )
            return None
        spec = entity_dto_to_stream_spec(entity)
        record = self._synthesizer.synthesize_record_by_id(
            spec,
            seed=cfg.seed,
            record_id=record_id,
        )
        logger.info(
            "universal_simulator_fetch_record_completed",
            tenant_id=cleaned_tenant_id,
            connection_id=cleaned_conn_id,
            stream_name=stream_name,
            record_id=record_id,
        )
        return record

    async def write_record(
        self,
        stream_name: str,
        command: WriteRecordCommand,
        public_config: JsonDict,
        credentials: JsonDict,
        *,
        tenant_id: str,
        connection_id: str,
    ) -> WriteResultDTO:
        """Destination Mode: Evaluates chaos rules and validates payload schema against the entity blueprint."""
        _ = credentials
        target_url = f"simulator://{self.APP_ID}/{stream_name}"
        scope_res = self._resolve_connection_scope(
            tenant_id=tenant_id,
            connection_id=connection_id,
            public_config=public_config,
        )
        if scope_res.is_err:
            err = scope_res.unwrap_err()
            category = SimulatorWriteFailureCategory.VALIDATION_ERROR
            logger.error(
                "universal_simulator_write_record_scope_invalid",
                stream_name=stream_name,
                record_id=command.record_id,
                error_code=err.code.value,
                failure_category=category.value,
            )
            return WriteResultDTO.from_error(
                err,
                record_id=command.record_id or category.value.lower(),
                target_url=target_url,
                response_status_code=err.http_status,
                failure_category=category.value,
            )

        cleaned_tenant_id, cleaned_conn_id, cfg, reader = scope_res.unwrap()
        target_url = f"simulator://{cleaned_conn_id}/{stream_name}"
        entity = await reader.get_entity_by_name(cleaned_tenant_id, cleaned_conn_id, stream_name)
        if entity is None:
            not_found_err = IpError(
                code=IpErrorCode.STREAM_NOT_FOUND,
                message=(
                    f"Simulator destination stream '{stream_name}' is not configured in "
                    f"connection '{cleaned_conn_id}'."
                ),
                http_status=404,
            )
            logger.error(
                "universal_simulator_write_record_stream_not_found",
                tenant_id=cleaned_tenant_id,
                connection_id=cleaned_conn_id,
                stream_name=stream_name,
                record_id=command.record_id,
            )
            return WriteResultDTO.from_error(
                not_found_err,
                record_id=command.record_id
                or SimulatorWriteFailureCategory.NOT_FOUND.value.lower(),
                target_url=target_url,
                response_status_code=404,
                failure_category=SimulatorWriteFailureCategory.NOT_FOUND.value,
            )

        spec = entity_dto_to_stream_spec(entity)
        if spec.chaos_policy.egress_http_error_rate_percent > 0.0:
            payload_fingerprint = hashlib.sha256(
                json.dumps(command.payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()[:16]
            record_identity = (
                command.record_id or command.idempotency_key or f"payload:{payload_fingerprint}"
            )
            attempt = max(1, command.attempt_number)
            key_material = f"{cfg.seed}|{stream_name}|{record_identity}|attempt:{attempt}"
            roll = (
                int(hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:8], 16) % 1000
            ) / 10.0
            if roll < spec.chaos_policy.egress_http_error_rate_percent:
                rate_err = IpError(
                    code=IpErrorCode.RATE_LIMIT_EXCEEDED,
                    message="Simulated HTTP 429 Too Many Requests from Universal Schema Simulator.",
                    http_status=429,
                )
                logger.error(
                    "universal_simulator_write_record_chaos_rate_limited",
                    tenant_id=cleaned_tenant_id,
                    connection_id=cleaned_conn_id,
                    stream_name=stream_name,
                    record_id=command.record_id,
                    configured_error_rate_percent=spec.chaos_policy.egress_http_error_rate_percent,
                )
                return WriteResultDTO.from_error(
                    rate_err,
                    record_id=(
                        command.record_id
                        or SimulatorWriteFailureCategory.RATE_LIMITED.value.lower()
                    ),
                    target_url=target_url,
                    response_status_code=429,
                    retry_after_seconds=2,
                    failure_category=SimulatorWriteFailureCategory.RATE_LIMITED.value,
                )

        validation_res = self._synthesizer.validate_payload_against_schema(spec, command.payload)
        if validation_res.is_err:
            val_err = validation_res.unwrap_err()
            logger.error(
                "universal_simulator_write_record_schema_violation",
                tenant_id=cleaned_tenant_id,
                connection_id=cleaned_conn_id,
                stream_name=stream_name,
                record_id=command.record_id,
                reason=val_err.message,
            )
            return WriteResultDTO.from_error(
                val_err,
                record_id=(
                    command.record_id
                    or SimulatorWriteFailureCategory.SCHEMA_VIOLATION.value.lower()
                ),
                target_url=target_url,
                response_status_code=422,
                failure_category=SimulatorWriteFailureCategory.SCHEMA_VIOLATION.value,
            )

        resolved_id = str(
            command.record_id
            or command.payload.get(spec.primary_key_field)
            or f"sim_{stream_name}_dest"
        )
        destination_id = f"sim_dest_{resolved_id}"
        logger.info(
            "universal_simulator_write_record_completed",
            tenant_id=cleaned_tenant_id,
            connection_id=cleaned_conn_id,
            stream_name=stream_name,
            record_id=resolved_id,
            destination_id=destination_id,
        )
        return WriteResultDTO(
            success=True,
            record_id=resolved_id,
            destination_id=destination_id,
            target_url=target_url,
            http_method="POST",
            response_status_code=200,
            response_body={
                "status": SimulatorSubmissionStatus.ACCEPTED.value,
                "destination_id": destination_id,
            },
            duration_ms=max(1, spec.chaos_policy.egress_simulated_latency_ms or 5),
        )


__all__ = ["UniversalSchemaSimulatorConnector"]
