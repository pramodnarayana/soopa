"""Native First-Class Sandbox Connector for Smart Grid AMI (Advanced Metering Infrastructure).

Implements the Shopify Bogus Gateway pattern for the Energy sector, generating
ANSI C12.19, CIM, and Green Button compliant smart meter interval readings and grid topology.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Final

import structlog
from ip.engine.adapters.outbound.connectors.base_connector import BaseConnector
from ip.engine.ports.outbound.catalog_registry_port import CatalogAppSummaryDTO
from ip.engine.ports.outbound.connector_port import (
    AppSpecDTO,
    ConnectionCheckResultDTO,
    ConnectorPropertyDTO,
    DiscoveredCatalogDTO,
    RecordEnvelopeDTO,
    StreamFieldDTO,
    StreamSchemaDTO,
    WriteRecordCommand,
    WriteResultDTO,
)
from ip.solutions.connectors.sandbox.energy.generators.synthetic_ami_data import (
    SyntheticAmiDataGenerator,
)
from seedwork.domain.types import JsonDict

logger = structlog.get_logger(__name__)


def _extract_int(config: JsonDict, key: str, default: int) -> int:
    """Safely extracts and coerces an integer configuration parameter."""
    raw = config.get(key)
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    if isinstance(raw, float):
        return int(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            return int(raw.strip())
        except ValueError:
            return default
    return default


def _extract_float(config: JsonDict, key: str, default: float) -> float:
    """Safely extracts and coerces a float configuration parameter."""
    raw = config.get(key)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            return float(raw.strip())
        except ValueError:
            return default
    return default


class EnergyAmiSimulatorConnector(BaseConnector):
    """First-class Smart Grid AMI sandbox simulator connector for zero-credential pipeline testing."""

    APP_ID: Final[str] = "energy_ami_simulator"
    STREAM_INTERVAL_READS: Final[str] = "interval_reads"
    STREAM_SERVICE_POINTS: Final[str] = "service_points"
    MAX_SIMULATOR_METER_COUNT: Final[int] = 5_000

    @classmethod
    def default_catalog_summary(cls) -> CatalogAppSummaryDTO:
        return CatalogAppSummaryDTO(
            app_id=cls.APP_ID,
            display_name="Smart Grid AMI (Simulator)",
            category="ENERGY",
            auth_type="NO_AUTH",
            description=(
                "High-fidelity smart grid AMI simulator generating realistic 15-minute interval "
                "readings and service point topologies without external vendor credentials."
            ),
            connector_type="NATIVE_SIMULATOR",
        )

    @property
    def app_id(self) -> str:
        return self.APP_ID

    def spec(self) -> AppSpecDTO:
        """Exposes configurable feeder parameters for the UI Connection Modal."""
        return AppSpecDTO(
            app_id=self.APP_ID,
            display_name="Smart Grid AMI (Simulator)",
            auth_type="NO_AUTH",
            category="ENERGY",
            description=(
                "Pre-configured Smart Grid AMI simulator generating IEEE/CIM utility topology and master data. "
                "Requires zero external credentials; ready for immediate testing."
            ),
            properties=(
                ConnectorPropertyDTO(
                    name="meter_count",
                    label="Number of Smart Meters",
                    type="INTEGER",
                    required=True,
                    default=5,
                    description="Total number of simulated smart meters / service points deployed across the feeder.",
                ),
            ),
        )

    async def check(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> ConnectionCheckResultDTO:
        """Validates synthetic feeder connectivity instantaneously."""
        meter_count = _extract_int(public_config, "meter_count", default=5)
        if meter_count < 1 or meter_count > self.MAX_SIMULATOR_METER_COUNT:
            logger.error(
                "simulator_check_rejected_invalid_meter_count",
                app_id=self.APP_ID,
                meter_count=meter_count,
                max_allowed=self.MAX_SIMULATOR_METER_COUNT,
            )
            return ConnectionCheckResultDTO(
                success=False,
                status="FAILED",
                message=f"Invalid meter_count: {meter_count}. Must be between 1 and {self.MAX_SIMULATOR_METER_COUNT}.",
                error_code="INVALID_PARAMETER",
            )

        logger.info(
            "simulator_check_executed",
            app_id=self.APP_ID,
            meter_count=meter_count,
            status="SUCCEEDED",
        )
        return ConnectionCheckResultDTO.ok(
            f"Smart Grid AMI Simulator ready: Synthetic feeder online with {meter_count} simulated meter endpoints."
        )

    async def discover(
        self,
        connection_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
        *,
        tenant_id: str = "",
    ) -> DiscoveredCatalogDTO:
        """Discovers master data entities (service_points) with default canonical L3 transformation bindings."""
        _ = tenant_id
        streams = (
            StreamSchemaDTO(
                name=self.STREAM_SERVICE_POINTS,
                fields=(
                    StreamFieldDTO(name="service_point_id", data_type="STRING", nullable=False),
                    StreamFieldDTO(name="meter_serial", data_type="STRING", nullable=True),
                    StreamFieldDTO(name="customer_id", data_type="STRING", nullable=True),
                    StreamFieldDTO(name="service_address", data_type="STRING", nullable=True),
                    StreamFieldDTO(name="grid_region", data_type="STRING", nullable=True),
                    StreamFieldDTO(name="status", data_type="STRING", nullable=False),
                ),
                primary_key=("service_point_id",),
                cursor_field=None,
                supported_sync_modes=("FULL_REFRESH", "INCREMENTAL"),
                default_transformation_id="energy.ami_service_point",
                default_transformation_version=1,
            ),
        )
        return self.build_catalog_dto(connection_id=connection_id, streams=streams)

    def _resolve_generator(self, public_config: JsonDict) -> SyntheticAmiDataGenerator:
        # Deterministic seed: derived from explicit seed, or hashed string, or fallback to default
        raw_seed = public_config.get("seed")
        if isinstance(raw_seed, int) and not isinstance(raw_seed, bool):
            return SyntheticAmiDataGenerator(seed=raw_seed)
        if isinstance(raw_seed, str) and raw_seed.strip():
            seed = int(hashlib.sha256(raw_seed.strip().encode("utf-8")).hexdigest()[:8], 16)
            return SyntheticAmiDataGenerator(seed=seed)
        return SyntheticAmiDataGenerator(seed=42)

    async def list_objects(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        limit: int = 100,
        cursor: str | None = None,
        *,
        tenant_id: str = "",
        connection_id: str = "",
    ) -> Sequence[str]:
        """Lists discrete record keys from the simulated feeder."""
        _ = (tenant_id, connection_id)
        meter_count = min(
            max(1, _extract_int(public_config, "meter_count", default=5)),
            self.MAX_SIMULATOR_METER_COUNT,
        )
        gen = self._resolve_generator(public_config)
        service_points = gen.generate_service_points(count=meter_count)

        if stream_name == self.STREAM_SERVICE_POINTS:
            return [sp.service_point_id for sp in service_points][:limit]

        if stream_name == self.STREAM_INTERVAL_READS:
            intervals = _extract_int(public_config, "intervals_per_meter", default=24)
            readings = gen.generate_interval_readings(service_points, intervals_per_meter=intervals)
            return [f"{r.meter_serial}:{r.timestamp}" for r in readings][:limit]

        return ()

    async def read_stream(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        cursor: str | None = None,
        limit: int = 100,
        *,
        tenant_id: str = "",
        connection_id: str = "",
    ) -> AsyncIterator[RecordEnvelopeDTO]:
        """Streams synthetic Green Button / CIM interval readings and topologies."""
        _ = (tenant_id, connection_id)
        meter_count = min(
            max(1, _extract_int(public_config, "meter_count", default=5)),
            self.MAX_SIMULATOR_METER_COUNT,
        )
        intervals_per_meter = _extract_int(public_config, "intervals_per_meter", default=24)
        failure_rate = _extract_float(public_config, "failure_rate_percent", default=0.0)

        gen = self._resolve_generator(public_config)
        service_points = gen.generate_service_points(count=meter_count)
        emitted_count = 0

        logger.info(
            "simulator_stream_reading_started",
            app_id=self.APP_ID,
            stream_name=stream_name,
            meter_count=meter_count,
            intervals_per_meter=intervals_per_meter,
            has_cursor=cursor is not None,
        )

        if stream_name == self.STREAM_SERVICE_POINTS:
            emitted_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            for sp in service_points:
                if emitted_count >= limit:
                    break
                emitted_count += 1
                yield RecordEnvelopeDTO(
                    stream_name=stream_name,
                    record_id=sp.service_point_id,
                    data=sp.to_dict(),
                    emitted_at=emitted_at,
                    cursor_value=None,
                )
            logger.info(
                "simulator_stream_reading_completed",
                app_id=self.APP_ID,
                stream_name=stream_name,
                emitted_count=emitted_count,
            )
            return

        if stream_name == self.STREAM_INTERVAL_READS:
            readings = gen.generate_interval_readings(
                service_points,
                intervals_per_meter=intervals_per_meter,
                failure_rate_percent=failure_rate,
            )

            for r in readings:
                # If cursor is provided, filter for records strictly newer than cursor
                if cursor and r.timestamp <= cursor:
                    continue

                if emitted_count >= limit:
                    break
                emitted_count += 1
                yield RecordEnvelopeDTO(
                    stream_name=stream_name,
                    record_id=f"{r.meter_serial}:{r.timestamp}",
                    data=r.to_dict(),
                    emitted_at=r.timestamp,
                    cursor_value=r.timestamp,
                )
            logger.info(
                "simulator_stream_reading_completed",
                app_id=self.APP_ID,
                stream_name=stream_name,
                emitted_count=emitted_count,
            )
            return

    async def fetch_record(
        self,
        stream_name: str,
        record_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
        *,
        tenant_id: str = "",
        connection_id: str = "",
    ) -> RecordEnvelopeDTO | None:
        """Fetches a single synthetic record by its primary key."""
        _ = (tenant_id, connection_id)
        meter_count = _extract_int(public_config, "meter_count", default=5)
        gen = self._resolve_generator(public_config)
        service_points = gen.generate_service_points(count=meter_count)

        if stream_name == self.STREAM_SERVICE_POINTS:
            for sp in service_points:
                if sp.service_point_id == record_id:
                    return RecordEnvelopeDTO(
                        stream_name=stream_name,
                        record_id=sp.service_point_id,
                        data=sp.to_dict(),
                        emitted_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    )
            return None

        if stream_name == self.STREAM_INTERVAL_READS:
            parts = record_id.split(":", 1)
            target_meter = parts[0]
            target_ts = parts[1] if len(parts) > 1 else None

            intervals = _extract_int(public_config, "intervals_per_meter", default=24)
            readings = gen.generate_interval_readings(service_points, intervals_per_meter=intervals)
            for r in readings:
                if r.meter_serial == target_meter and (
                    target_ts is None or r.timestamp == target_ts
                ):
                    return RecordEnvelopeDTO(
                        stream_name=stream_name,
                        record_id=f"{r.meter_serial}:{r.timestamp}",
                        data=r.to_dict(),
                        emitted_at=r.timestamp,
                        cursor_value=r.timestamp,
                    )
            return None

        return None

    async def write_record(
        self,
        stream_name: str,
        command: WriteRecordCommand,
        public_config: JsonDict,
        credentials: JsonDict,
        *,
        tenant_id: str = "",
        connection_id: str = "",
    ) -> WriteResultDTO:
        """Write operations are rejected as this connector is a read-only interval data source."""
        _ = (tenant_id, connection_id)
        return WriteResultDTO(
            success=False,
            record_id=command.record_id or "unsupported",
            error_message="Smart Grid AMI Simulator is a read-only ingress source.",
            failure_category="UNSUPPORTED_OPERATION",
        )
