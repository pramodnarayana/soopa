"""First-Class Universal Schema-Driven Sandbox Simulator Connector (`ConnectorPort` implementation)."""

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
from ip.solutions.connectors.sandbox.universal.dto import (
    SimulatorSandboxDTO,
    entity_dto_to_stream_spec,
)
from ip.solutions.connectors.sandbox.universal.inference import (
    extract_stream_schema_dto,
    parse_simulator_connection_config,
)
from ip.solutions.connectors.sandbox.universal.ports import SimulatorSandboxReaderPort
from ip.solutions.connectors.sandbox.universal.spec import (
    SimulatorConnectionConfig,
    SimulatorSubmissionStatus,
    SimulatorWriteFailureCategory,
)
from ip.solutions.connectors.sandbox.universal.synthesizer import JsonSchemaRecordSynthesizer
from seedwork.domain.types import JsonDict

logger = structlog.get_logger(__name__)


class UniversalSchemaSimulatorConnector(BaseConnector):
    """Domain-agnostic JSON-Schema-driven virtual external system connector."""

    APP_ID: Final[str] = "universal_simulator"

    def __init__(
        self,
        *,
        sandbox_reader: SimulatorSandboxReaderPort | None = None,
        synthesizer: JsonSchemaRecordSynthesizer | None = None,
    ) -> None:
        self._sandbox_reader = sandbox_reader
        self._synthesizer = synthesizer or JsonSchemaRecordSynthesizer()

    @classmethod
    def default_catalog_summary(cls) -> CatalogAppSummaryDTO:
        return CatalogAppSummaryDTO(
            app_id=cls.APP_ID,
            display_name="Universal Sandbox Simulator",
            category=CatalogCategory.SANDBOX,
            auth_type=AuthType.API_KEY,
            description=(
                "Virtual external system simulator authenticated via Sandbox ID and API Key. "
                "Configure custom JSON Schema entities inside a Virtual Sandbox and test Pull, "
                "Push, and Outbound Delivery flows."
            ),
            connector_type=ConnectorArchitectureType.NATIVE_SIMULATOR,
        )

    @property
    def app_id(self) -> str:
        return self.APP_ID

    def spec(self) -> AppSpecDTO:
        """Exposes `sandbox_id`, `api_key`, `seed`, and `records_per_pull` for Component 1 Connections."""
        return AppSpecDTO(
            app_id=self.APP_ID,
            display_name="Universal Sandbox Simulator",
            auth_type=AuthType.API_KEY,
            category=CatalogCategory.SANDBOX,
            description=(
                "Connects to an isolated Virtual Sandbox using its Sandbox ID and secret API Key. "
                "Entities configured in the Virtual Sandbox are discovered via Component 2 Catalog Discovery."
            ),
            properties=(
                ConnectorPropertyDTO(
                    name="sandbox_id",
                    label="Virtual Sandbox ID",
                    type=PropertyType.SHORT_TEXT,
                    required=True,
                    description="Identifier of the Virtual Sandbox environment to connect to (e.g. sbx_...).",
                ),
                ConnectorPropertyDTO(
                    name="api_key",
                    label="Sandbox API Key",
                    type=PropertyType.SECRET_TEXT,
                    required=True,
                    description="Secret API key issued when the Virtual Sandbox was provisioned (e.g. sbx_key_...).",
                ),
                ConnectorPropertyDTO(
                    name="seed",
                    label="Deterministic PRNG Seed",
                    type=PropertyType.NUMBER,
                    required=False,
                    default=42,
                    description="Seed used for deterministic synthetic record generation.",
                ),
                ConnectorPropertyDTO(
                    name="records_per_pull",
                    label="Default Records per Pull",
                    type=PropertyType.NUMBER,
                    required=False,
                    default=25,
                    description="Default number of synthetic records emitted on each pull sync run.",
                ),
            ),
        )

    async def _authenticate_sandbox(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> Result[tuple[SimulatorConnectionConfig, SimulatorSandboxDTO], IpError]:
        cfg = parse_simulator_connection_config(public_config)
        if self._sandbox_reader is None:
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name="sandbox_id",
                    message="Virtual sandbox reader is not initialized on UniversalSchemaSimulatorConnector.",
                )
            )
        raw_api_key = str(credentials.get("api_key") or "")
        auth_res = await self._sandbox_reader.authenticate_sandbox(
            sandbox_id=cfg.sandbox_id,
            raw_api_key=raw_api_key,
        )
        if auth_res.is_err:
            return Result.fail(auth_res.unwrap_err())
        return Result.ok((cfg, auth_res.unwrap()))

    async def check(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> ConnectionCheckResultDTO:
        """Authenticates `(sandbox_id, api_key)` against `ip.simulator_sandboxes`."""
        auth_res = await self._authenticate_sandbox(public_config, credentials)
        if auth_res.is_err:
            err = auth_res.unwrap_err()
            logger.error(
                "universal_simulator_check_failed",
                app_id=self.APP_ID,
                error_code=err.code.value,
                reason=err.message,
            )
            return ConnectionCheckResultDTO.from_error(err)

        cfg, sandbox = auth_res.unwrap()
        entities = (
            await self._sandbox_reader.list_entities_by_sandbox(sandbox.id)
            if self._sandbox_reader is not None
            else ()
        )
        logger.info(
            "universal_simulator_check_succeeded",
            app_id=self.APP_ID,
            sandbox_id=sandbox.id,
            seed=cfg.seed,
            configured_entity_count=len(entities),
        )
        return ConnectionCheckResultDTO.ok(
            f"Connected to Virtual Sandbox '{sandbox.name}' ({sandbox.id}, entities={len(entities)})."
        )

    async def discover(
        self,
        connection_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> DiscoveredCatalogDTO:
        """Authenticates the Virtual Sandbox and translates its `ip.simulator_entities` into `StreamSchemaDTO`s."""
        auth_res = await self._authenticate_sandbox(public_config, credentials)
        if auth_res.is_err:
            err = auth_res.unwrap_err()
            logger.error(
                "universal_simulator_discover_failed",
                connection_id=connection_id,
                error_code=err.code.value,
                reason=err.message,
            )
            return DiscoveredCatalogDTO.from_error(connection_id, err)

        _, sandbox = auth_res.unwrap()
        entities = (
            await self._sandbox_reader.list_entities_by_sandbox(sandbox.id)
            if self._sandbox_reader is not None
            else ()
        )
        streams: list[StreamSchemaDTO] = [
            extract_stream_schema_dto(entity_dto_to_stream_spec(entity)) for entity in entities
        ]
        logger.info(
            "universal_simulator_discover_completed",
            connection_id=connection_id,
            sandbox_id=sandbox.id,
            discovered_stream_count=len(streams),
            streams=[s.name for s in streams],
        )
        return self.build_catalog_dto(connection_id=connection_id, streams=tuple(streams))

    async def list_objects(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Sequence[str]:
        """Authenticates the Virtual Sandbox and lists synthetic object IDs for `stream_name`."""
        self._last_error = None
        auth_res = await self._authenticate_sandbox(public_config, credentials)
        if auth_res.is_err:
            err = auth_res.unwrap_err()
            self._last_error = err
            logger.error(
                "universal_simulator_list_objects_auth_failed",
                stream_name=stream_name,
                error_code=err.code.value,
                reason=err.message,
            )
            return ()
        cfg, sandbox = auth_res.unwrap()
        entity = (
            await self._sandbox_reader.get_entity_by_name(sandbox.id, stream_name)
            if self._sandbox_reader is not None
            else None
        )
        if entity is None:
            logger.error(
                "universal_simulator_list_objects_stream_not_found",
                sandbox_id=sandbox.id,
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
            sandbox_id=sandbox.id,
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
    ) -> AsyncIterator[RecordEnvelopeDTO]:
        """Pull Mode: Authenticates the Virtual Sandbox and synthesizes records newer than `cursor`."""
        self._last_error = None
        auth_res = await self._authenticate_sandbox(public_config, credentials)
        if auth_res.is_err:
            err = auth_res.unwrap_err()
            self._last_error = err
            logger.error(
                "universal_simulator_read_stream_auth_failed",
                stream_name=stream_name,
                error_code=err.code.value,
                reason=err.message,
            )
            return

        cfg, sandbox = auth_res.unwrap()
        entity = (
            await self._sandbox_reader.get_entity_by_name(sandbox.id, stream_name)
            if self._sandbox_reader is not None
            else None
        )
        if entity is None:
            not_found_err = IpError(
                code=IpErrorCode.STREAM_NOT_FOUND,
                message=f"Entity '{stream_name}' is not configured in Virtual Sandbox '{sandbox.id}'.",
                http_status=404,
            )
            self._last_error = not_found_err
            logger.error(
                "universal_simulator_read_stream_not_found",
                sandbox_id=sandbox.id,
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
            sandbox_id=sandbox.id,
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
    ) -> RecordEnvelopeDTO | None:
        """Thin-Push Fetch Mode: Authenticates the Virtual Sandbox and reconstructs `record_id`."""
        self._last_error = None
        auth_res = await self._authenticate_sandbox(public_config, credentials)
        if auth_res.is_err:
            err = auth_res.unwrap_err()
            self._last_error = err
            logger.error(
                "universal_simulator_fetch_record_auth_failed",
                stream_name=stream_name,
                record_id=record_id,
                error_code=err.code.value,
                reason=err.message,
            )
            return None
        cfg, sandbox = auth_res.unwrap()
        entity = (
            await self._sandbox_reader.get_entity_by_name(sandbox.id, stream_name)
            if self._sandbox_reader is not None
            else None
        )
        if entity is None:
            logger.error(
                "universal_simulator_fetch_record_stream_not_found",
                sandbox_id=sandbox.id,
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
            sandbox_id=sandbox.id,
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
    ) -> WriteResultDTO:
        """Destination Mode: Authenticates the Virtual Sandbox, evaluates chaos rules, and validates payload schema."""
        target_url = f"simulator://{self.APP_ID}/{stream_name}"
        auth_res = await self._authenticate_sandbox(public_config, credentials)
        if auth_res.is_err:
            err = auth_res.unwrap_err()
            category = (
                SimulatorWriteFailureCategory.AUTH_ERROR
                if err.http_status in (401, 403)
                else SimulatorWriteFailureCategory.VALIDATION_ERROR
            )
            logger.error(
                "universal_simulator_write_record_auth_failed",
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

        cfg, sandbox = auth_res.unwrap()
        target_url = f"simulator://{sandbox.id}/{stream_name}"
        entity = (
            await self._sandbox_reader.get_entity_by_name(sandbox.id, stream_name)
            if self._sandbox_reader is not None
            else None
        )
        if entity is None:
            not_found_err = IpError(
                code=IpErrorCode.STREAM_NOT_FOUND,
                message=(
                    f"Simulator destination stream '{stream_name}' is not configured in "
                    f"Virtual Sandbox '{sandbox.id}'."
                ),
                http_status=404,
            )
            logger.error(
                "universal_simulator_write_record_stream_not_found",
                sandbox_id=sandbox.id,
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
                    message="Simulated HTTP 429 Too Many Requests from Universal Sandbox Simulator.",
                    http_status=429,
                )
                logger.error(
                    "universal_simulator_write_record_chaos_rate_limited",
                    sandbox_id=sandbox.id,
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
                sandbox_id=sandbox.id,
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
            sandbox_id=sandbox.id,
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
