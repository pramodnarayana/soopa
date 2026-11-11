"""First-Class Universal Schema-Driven Sandbox Simulator Connector (`ConnectorPort` implementation)."""

from __future__ import annotations

import hashlib
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
from ip.engine.domain.exceptions import IpError, IpErrorCode
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
from ip.solutions.connectors.sandbox.universal.inference import (
    extract_stream_schema_dto,
    parse_simulator_manifest,
)
from ip.solutions.connectors.sandbox.universal.synthesizer import JsonSchemaRecordSynthesizer
from seedwork.domain.types import JsonDict

logger = structlog.get_logger(__name__)


class UniversalSchemaSimulatorConnector(BaseConnector):
    """Domain-agnostic JSON-Schema-driven source and destination sandbox simulator connector."""

    APP_ID: Final[str] = "universal_simulator"

    def __init__(self, synthesizer: JsonSchemaRecordSynthesizer | None = None) -> None:
        self._synthesizer = synthesizer or JsonSchemaRecordSynthesizer()

    @classmethod
    def default_catalog_summary(cls) -> CatalogAppSummaryDTO:
        return CatalogAppSummaryDTO(
            app_id=cls.APP_ID,
            display_name="Universal Sandbox Simulator",
            category=CatalogCategory.SANDBOX,
            auth_type=AuthType.NO_AUTH,
            description=(
                "Zero-credential universal sandbox simulator. Create custom entities by uploading "
                "any sample JSON or JSON Schema and test Pull, Push, and Hybrid reconciliation flows."
            ),
            connector_type=ConnectorArchitectureType.NATIVE_SIMULATOR,
        )

    @property
    def app_id(self) -> str:
        return self.APP_ID

    def spec(self) -> AppSpecDTO:
        """Exposes optional seed and pull batch size parameters for the UI Connection Modal."""
        return AppSpecDTO(
            app_id=self.APP_ID,
            display_name="Universal Sandbox Simulator",
            auth_type=AuthType.NO_AUTH,
            category=CatalogCategory.SANDBOX,
            description=(
                "Connects immediately without credentials. After connecting, create any number of "
                "entities by uploading sample .json files, then discover and sync via Pull or Push."
            ),
            properties=(
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

    async def check(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> ConnectionCheckResultDTO:
        """Validates `public_config` manifest syntax if entities are already present; succeeds immediately on connect."""
        manifest_res = parse_simulator_manifest(public_config)
        if manifest_res.is_err:
            err = manifest_res.unwrap_err()
            logger.error(
                "universal_simulator_check_failed",
                app_id=self.APP_ID,
                error_code=err.code.value,
                reason=err.message,
            )
            return ConnectionCheckResultDTO.from_error(err)

        manifest = manifest_res.unwrap()
        stream_count = len(manifest.streams)
        logger.info(
            "universal_simulator_check_succeeded",
            app_id=self.APP_ID,
            seed=manifest.seed,
            configured_stream_count=stream_count,
        )
        return ConnectionCheckResultDTO.ok(
            f"Universal Sandbox Simulator connected (seed={manifest.seed}, entities={stream_count})."
        )

    async def discover(
        self,
        connection_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> DiscoveredCatalogDTO:
        """Discovers all user-created entities in `public_config['streams']` and converts them to `StreamSchemaDTO`s."""
        manifest_res = parse_simulator_manifest(public_config)
        if manifest_res.is_err:
            err = manifest_res.unwrap_err()
            logger.error(
                "universal_simulator_discover_failed",
                connection_id=connection_id,
                error_code=err.code.value,
                reason=err.message,
            )
            return DiscoveredCatalogDTO.from_error(connection_id, err)

        manifest = manifest_res.unwrap()
        streams: list[StreamSchemaDTO] = [
            extract_stream_schema_dto(spec) for spec in manifest.streams.values()
        ]
        logger.info(
            "universal_simulator_discover_completed",
            connection_id=connection_id,
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
        """Lists synthetic object IDs for the requested entity stream."""
        manifest_res = parse_simulator_manifest(public_config)
        if manifest_res.is_err:
            return ()
        manifest = manifest_res.unwrap()
        spec = manifest.streams.get(stream_name)
        if spec is None:
            return ()
        batch = self._synthesizer.synthesize_batch(
            spec,
            seed=manifest.seed,
            cursor=cursor,
            limit=min(limit, spec.records_per_pull),
        )
        return tuple(env.record_id for env in batch)

    async def read_stream(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        cursor: str | None = None,
        limit: int = 100,
    ) -> AsyncIterator[RecordEnvelopeDTO]:
        """Pull Mode: Synthesizes records on-the-fly with timestamps strictly newer than `cursor`."""
        manifest_res = parse_simulator_manifest(public_config)
        if manifest_res.is_err:
            err = manifest_res.unwrap_err()
            logger.error(
                "universal_simulator_read_stream_manifest_invalid",
                stream_name=stream_name,
                error_code=err.code.value,
            )
            return

        manifest = manifest_res.unwrap()
        spec = manifest.streams.get(stream_name)
        if spec is None:
            logger.error(
                "universal_simulator_read_stream_not_found",
                stream_name=stream_name,
                available_streams=list(manifest.streams.keys()),
            )
            return

        effective_limit = min(max(1, limit), spec.records_per_pull)
        batch = self._synthesizer.synthesize_batch(
            spec,
            seed=manifest.seed,
            cursor=cursor,
            limit=effective_limit,
        )
        logger.info(
            "universal_simulator_read_stream_completed",
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
        """Thin-Push Fetch Mode: Deterministically reconstructs the exact record for `record_id`."""
        manifest_res = parse_simulator_manifest(public_config)
        if manifest_res.is_err:
            return None
        manifest = manifest_res.unwrap()
        spec = manifest.streams.get(stream_name)
        if spec is None:
            return None
        return self._synthesizer.synthesize_record_by_id(
            spec,
            seed=manifest.seed,
            record_id=record_id,
        )

    async def write_record(
        self,
        stream_name: str,
        command: WriteRecordCommand,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> WriteResultDTO:
        """Destination Mode: Validates outbound payload against the stream's JSON Schema and evaluates chaos rules."""
        target_url = f"simulator://{self.APP_ID}/{stream_name}"
        manifest_res = parse_simulator_manifest(public_config)
        if manifest_res.is_err:
            err = manifest_res.unwrap_err()
            return WriteResultDTO.from_error(
                err,
                record_id=command.record_id or "invalid",
                target_url=target_url,
                response_status_code=422,
                failure_category="VALIDATION_ERROR",
            )

        manifest = manifest_res.unwrap()
        spec = manifest.streams.get(stream_name)
        if spec is None:
            not_found_err = IpError(
                code=IpErrorCode.STREAM_NOT_FOUND,
                message=f"Simulator destination stream '{stream_name}' is not configured.",
                http_status=404,
            )
            return WriteResultDTO.from_error(
                not_found_err,
                record_id=command.record_id or "not_found",
                target_url=target_url,
                response_status_code=404,
                failure_category="NOT_FOUND",
            )

        # Evaluate Egress Chaos Policy if configured
        if spec.chaos_policy.egress_http_error_rate_percent > 0.0:
            key_material = f"{manifest.seed}|{stream_name}|{command.record_id or command.idempotency_key or ''}"
            roll = (
                int(hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:8], 16) % 1000
            ) / 10.0
            if roll < spec.chaos_policy.egress_http_error_rate_percent:
                rate_err = IpError(
                    code=IpErrorCode.RATE_LIMIT_EXCEEDED,
                    message="Simulated HTTP 429 Too Many Requests from Universal Sandbox Simulator.",
                    http_status=429,
                )
                return WriteResultDTO.from_error(
                    rate_err,
                    record_id=command.record_id or "rate_limited",
                    target_url=target_url,
                    response_status_code=429,
                    retry_after_seconds=2,
                    failure_category="RATE_LIMITED",
                )

        validation_res = self._synthesizer.validate_payload_against_schema(spec, command.payload)
        if validation_res.is_err:
            val_err = validation_res.unwrap_err()
            return WriteResultDTO.from_error(
                val_err,
                record_id=command.record_id or "schema_violation",
                target_url=target_url,
                response_status_code=422,
                failure_category="SCHEMA_VIOLATION",
            )

        resolved_id = str(
            command.record_id
            or command.payload.get(spec.primary_key_field)
            or f"sim_{stream_name}_dest"
        )
        return WriteResultDTO(
            success=True,
            record_id=resolved_id,
            destination_id=f"sim_dest_{resolved_id}",
            target_url=target_url,
            http_method="POST",
            response_status_code=200,
            response_body={"status": "ACCEPTED", "destination_id": f"sim_dest_{resolved_id}"},
            duration_ms=max(1, spec.chaos_policy.egress_simulated_latency_ms or 5),
        )


__all__ = ["UniversalSchemaSimulatorConnector"]
