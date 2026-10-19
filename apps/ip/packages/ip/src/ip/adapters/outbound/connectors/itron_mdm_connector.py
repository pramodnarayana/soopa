"""Production Energy MDM connector for Smart Grid AMI Head-End Systems (Itron/Sensus style)."""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import httpx
import structlog
from ip.adapters.outbound.connectors.base_connector import BaseConnector
from ip.application.responses import (
    ConnectionCheckResultDTO,
    DiscoveredCatalogDTO,
    RecordEnvelopeDTO,
    StreamFieldDTO,
    StreamSchemaDTO,
    WriteRecordCommand,
    WriteResultDTO,
)
from ip.domain.types import JsonDict

logger = structlog.get_logger(__name__)


class ItronMdmConnector(BaseConnector):
    """Production Energy MDM Connector communicating over HTTP REST with AMI Head-End systems."""

    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self._timeout_seconds = timeout_seconds

    @property
    def app_id(self) -> str:
        return "itron_mdm"

    def spec(self) -> JsonDict:
        return {
            "type": "object",
            "required": ["endpoint_url", "api_key"],
            "properties": {
                "endpoint_url": {
                    "type": "string",
                    "title": "Head-End API URL",
                    "description": "Base URL of the Itron AMI head-end server",
                    "format": "uri",
                },
                "api_key": {
                    "type": "string",
                    "title": "AMI Access Key",
                    "description": "Secret API token for AMI system authentication",
                    "writeOnly": True,
                },
                "region": {
                    "type": "string",
                    "title": "Grid Operating Region",
                    "default": "US-EAST",
                },
            },
        }

    def _get_headers(self, credentials: JsonDict) -> dict[str, str]:
        api_key = str(credentials.get("api_key", ""))
        return {
            "X-API-Key": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def check(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> ConnectionCheckResultDTO:
        endpoint = str(public_config.get("endpoint_url", "")).rstrip("/")
        api_key = str(credentials.get("api_key", ""))

        if not endpoint:
            return ConnectionCheckResultDTO(
                success=False,
                status="FAILED",
                message="Missing required field: endpoint_url",
                error_code="INVALID_CONFIG",
            )

        if not api_key:
            return ConnectionCheckResultDTO(
                success=False,
                status="FAILED",
                message="Missing required credential: api_key",
                error_code="INVALID_CREDENTIALS",
            )

        health_url = f"{endpoint}/api/v1/health"
        headers = self._get_headers(credentials)

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(health_url, headers=headers)

                if response.status_code == 200:
                    return ConnectionCheckResultDTO(
                        success=True,
                        status="SUCCEEDED",
                        message="Connection to Itron MDM system established successfully.",
                    )
                if response.status_code in (401, 403):
                    return ConnectionCheckResultDTO(
                        success=False,
                        status="FAILED",
                        message="Authentication failed: Invalid AMI access key.",
                        error_code="UNAUTHORIZED",
                    )
                return ConnectionCheckResultDTO(
                    success=False,
                    status="FAILED",
                    message=f"Itron MDM returned HTTP {response.status_code}",
                    error_code="HTTP_ERROR",
                )
        except httpx.RequestError as exc:
            logger.warning("itron_mdm_check_network_failure", endpoint=endpoint, error=str(exc))
            return ConnectionCheckResultDTO(
                success=False,
                status="FAILED",
                message=f"Network error connecting to {endpoint}: {exc}",
                error_code="NETWORK_ERROR",
            )

    async def discover(
        self,
        connection_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> DiscoveredCatalogDTO:
        endpoint = str(public_config.get("endpoint_url", "")).rstrip("/")
        schema_url = f"{endpoint}/api/v1/schema/streams"
        headers = self._get_headers(credentials)

        streams: list[StreamSchemaDTO] = []
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(schema_url, headers=headers)
                if response.status_code == 200:
                    payload = response.json()
                    for s in payload.get("streams", []):
                        fields = [
                            StreamFieldDTO(
                                name=f["name"],
                                data_type=f["data_type"],
                                nullable=f.get("nullable", True),
                                description=f.get("description"),
                            )
                            for f in s.get("fields", [])
                        ]
                        streams.append(
                            StreamSchemaDTO(
                                name=s["name"],
                                fields=fields,
                                primary_key=list(s.get("primary_key", ["id"])),
                                cursor_field=s.get("cursor_field"),
                                supported_sync_modes=tuple(
                                    s.get("supported_sync_modes", ["FULL_REFRESH", "INCREMENTAL"])
                                ),
                            )
                        )
        except httpx.RequestError as exc:
            logger.warning("itron_mdm_schema_discovery_fallback", endpoint=endpoint, error=str(exc))

        # Default canonical Itron AMI stream definitions if remote introspection endpoint is absent
        if not streams:
            streams = [
                StreamSchemaDTO(
                    name="meters",
                    fields=[
                        StreamFieldDTO(name="id", data_type="string", nullable=False),
                        StreamFieldDTO(name="serial_number", data_type="string", nullable=False),
                        StreamFieldDTO(name="model", data_type="string"),
                        StreamFieldDTO(name="status", data_type="string"),
                        StreamFieldDTO(name="last_reading_time", data_type="datetime"),
                    ],
                    primary_key=["id"],
                    cursor_field="last_reading_time",
                ),
                StreamSchemaDTO(
                    name="interval_reads",
                    fields=[
                        StreamFieldDTO(name="meter_id", data_type="string", nullable=False),
                        StreamFieldDTO(name="timestamp", data_type="datetime", nullable=False),
                        StreamFieldDTO(name="kwh_delivered", data_type="number", nullable=False),
                        StreamFieldDTO(name="kwh_received", data_type="number"),
                        StreamFieldDTO(name="quality", data_type="string"),
                    ],
                    primary_key=["meter_id", "timestamp"],
                    cursor_field="timestamp",
                ),
                StreamSchemaDTO(
                    name="service_points",
                    fields=[
                        StreamFieldDTO(name="id", data_type="string", nullable=False),
                        StreamFieldDTO(name="address", data_type="string"),
                        StreamFieldDTO(name="customer_id", data_type="string"),
                        StreamFieldDTO(name="meter_id", data_type="string"),
                    ],
                    primary_key=["id"],
                ),
            ]

        return self.build_catalog_dto(connection_id, streams)

    async def list_objects(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Sequence[str]:
        endpoint = str(public_config.get("endpoint_url", "")).rstrip("/")
        url = f"{endpoint}/api/v1/streams/{stream_name}/ids"
        headers = self._get_headers(credentials)
        params: dict[str, str | int] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            return [str(item) for item in data.get("ids", [])]

    async def read_stream(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        cursor: str | None = None,
        limit: int = 100,
    ) -> AsyncIterator[RecordEnvelopeDTO]:
        endpoint = str(public_config.get("endpoint_url", "")).rstrip("/")
        url = f"{endpoint}/api/v1/streams/{stream_name}/records"
        headers = self._get_headers(credentials)
        params: dict[str, str | int] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            payload = resp.json()

        for item in payload.get("records", []):
            rec_id = str(item.get("id") or item.get("meter_id", ""))
            yield RecordEnvelopeDTO(
                stream_name=stream_name,
                record_id=rec_id,
                data=item,
                emitted_at=datetime.now(UTC).isoformat(),
            )

    async def write_record(
        self,
        stream_name: str,
        command: WriteRecordCommand,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> WriteResultDTO:
        endpoint = str(public_config.get("endpoint_url", "")).rstrip("/")
        url = f"{endpoint}/api/v1/streams/{stream_name}/records"
        headers = self._get_headers(credentials)

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                resp = await client.post(url, headers=headers, json=command.payload)
                resp.raise_for_status()
                data = resp.json()
                return WriteResultDTO(
                    success=True,
                    record_id=str(data.get("id", "written_rec")),
                    destination_id=str(data.get("destination_id", f"{self.app_id}_{stream_name}")),
                )
        except httpx.HTTPStatusError as exc:
            return WriteResultDTO(
                success=False,
                record_id="failed",
                error_message=f"HTTP {exc.response.status_code}: {exc.response.text}",
            )
        except httpx.RequestError as exc:
            return WriteResultDTO(
                success=False,
                record_id="failed",
                error_message=f"Network error: {exc}",
            )
