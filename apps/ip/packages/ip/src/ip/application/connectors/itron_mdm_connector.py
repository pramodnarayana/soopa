"""Production Energy MDM connector for Smart Grid AMI Head-End Systems (Itron/Sensus style)."""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import httpx
import structlog
from ip.engine.adapters.outbound.connectors.base_connector import BaseConnector
from ip.engine.application.responses import (
    AppSpecDTO,
    CatalogAppSummaryDTO,
    ConnectionCheckResultDTO,
    ConnectorPropertyDTO,
    DiscoveredCatalogDTO,
    RecordEnvelopeDTO,
    StreamFieldDTO,
    StreamSchemaDTO,
    WriteRecordCommand,
    WriteResultDTO,
)
from ip.engine.domain.exceptions import (
    AuthenticationFailedError,
    EndpointSecurityViolationError,
    InvalidConnectionConfigError,
    InvalidCredentialsError,
    InvalidEndpointError,
    IpErrorCode,
    Result,
    UnsupportedWriteOperationError,
    UpstreamHttpError,
    UpstreamNetworkError,
    UpstreamRemoteError,
)
from seedwork.domain.types import JsonDict
from shttp import HttpClient, HttpError, PassThroughPolicy, create_http_client

logger = structlog.get_logger(__name__)


class ItronMdmConnector(BaseConnector):
    """Production Energy MDM Connector communicating over HTTP REST with AMI Head-End systems."""

    @classmethod
    def default_catalog_summary(cls) -> CatalogAppSummaryDTO:
        return CatalogAppSummaryDTO(
            app_id="itron_mdm",
            display_name="Itron OpenWay Riva MDM",
            category="ENERGY",
            auth_type="API_KEY",
            description="Smart Grid AMI Head-End and Meter Data Management (MDM) connector",
            connector_type="CUSTOM_PYTHON",
        )

    def __init__(
        self,
        timeout_seconds: float = 10.0,
        http_client: HttpClient | None = None,
        allow_private_ips: bool = False,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._allow_private_ips = allow_private_ips
        if http_client is not None:
            self._http_client = http_client
        else:
            raw_client = create_http_client(timeout=timeout_seconds)
            self._http_client = HttpClient(
                client=raw_client,
                allow_private_ips=allow_private_ips,
                response_policy=PassThroughPolicy(),
            )

    @property
    def app_id(self) -> str:
        return "itron_mdm"

    def spec(self) -> AppSpecDTO:
        return AppSpecDTO(
            app_id=self.app_id,
            display_name="Itron OpenWay Riva MDM",
            auth_type="API_KEY",
            category="ENERGY",
            description="Smart Grid Advanced Metering Infrastructure (AMI) Head-End Gateway",
            properties=(
                ConnectorPropertyDTO(
                    name="endpoint_url",
                    label="Head-End API URL",
                    type="shortText",
                    required=True,
                    description="Base URL of the Itron AMI head-end server",
                ),
                ConnectorPropertyDTO(
                    name="api_key",
                    label="AMI Access Key",
                    type="secretText",
                    required=True,
                    description="Secret API token for AMI system authentication",
                ),
                ConnectorPropertyDTO(
                    name="region",
                    label="Grid Operating Region",
                    type="shortText",
                    required=False,
                    default="US-EAST",
                ),
            ),
        )

    @staticmethod
    def _validate_endpoint(
        endpoint: str,
    ) -> Result[
        str,
        InvalidConnectionConfigError | InvalidEndpointError | EndpointSecurityViolationError,
    ]:
        return BaseConnector.validate_http_endpoint_url(
            endpoint,
            allow_private_ips=False,
            enforce_ssrf_precheck=False,
            disallow_query_or_fragment=True,
            error_code=IpErrorCode.INVALID_CONFIG,
            field_name="endpoint_url",
        )

    def _get_headers(self, credentials: JsonDict) -> dict[str, str]:
        api_key = str(credentials.get("api_key", ""))
        return {
            "X-API-Key": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _get_default_streams() -> list[StreamSchemaDTO]:
        return [
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

    async def check(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> ConnectionCheckResultDTO:
        endpoint_res = self._validate_endpoint(str(public_config.get("endpoint_url", "")))
        if endpoint_res.error is not None or endpoint_res.value is None:
            err = endpoint_res.error or InvalidConnectionConfigError(
                field_name="endpoint_url",
                message="Invalid endpoint_url",
            )
            return ConnectionCheckResultDTO.from_error(
                err,
                error_code_override=IpErrorCode.INVALID_CONFIG.value,
            )

        endpoint = endpoint_res.value
        api_key = str(credentials.get("api_key", ""))
        if not api_key:
            return ConnectionCheckResultDTO.from_error(
                InvalidCredentialsError(
                    field_name="api_key",
                    message="Missing required credential: api_key",
                )
            )

        health_url = f"{endpoint}/api/v1/health"
        headers = self._get_headers(credentials)

        try:
            response = await self._http_client.get(
                health_url, headers=headers, timeout=self._timeout_seconds
            )

            if response.status_code == 200:
                return ConnectionCheckResultDTO.ok(
                    "Connection to Itron MDM system established successfully."
                )
            if response.status_code in (401, 403):
                return ConnectionCheckResultDTO.from_error(
                    AuthenticationFailedError(
                        app_id=self.app_id,
                        status_code=response.status_code,
                        message="Authentication failed: Invalid AMI access key.",
                    )
                )
            return ConnectionCheckResultDTO.from_error(
                UpstreamHttpError(
                    status_code=response.status_code,
                    message=f"Itron MDM returned HTTP {response.status_code}",
                )
            )
        except (HttpError, httpx.HTTPError, OSError, ValueError) as exc:
            logger.error("itron_mdm_check_network_failure", endpoint=endpoint, error=str(exc))
            return ConnectionCheckResultDTO.from_error(
                UpstreamNetworkError(
                    endpoint=endpoint,
                    message=f"Network error connecting to {endpoint}: {exc}",
                )
            )

    async def discover(
        self,
        connection_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> DiscoveredCatalogDTO:
        raw_endpoint = str(public_config.get("endpoint_url", ""))
        endpoint_res = self._validate_endpoint(raw_endpoint)
        if endpoint_res.error is not None or endpoint_res.value is None:
            msg = endpoint_res.error.message if endpoint_res.error else "Invalid endpoint URL"
            logger.error("itron_mdm_invalid_endpoint", error=msg)
            return DiscoveredCatalogDTO.from_error(
                connection_id,
                InvalidEndpointError(
                    endpoint=raw_endpoint,
                    message=f"Invalid endpoint URL for Itron MDM schema discovery: {msg}",
                ),
            )

        endpoint = endpoint_res.value
        schema_url = f"{endpoint}/api/v1/schema/streams"
        headers = self._get_headers(credentials)

        streams: list[StreamSchemaDTO] = []
        try:
            response = await self._http_client.get(
                schema_url, headers=headers, timeout=self._timeout_seconds
            )
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
            elif response.status_code == 404:
                logger.info("itron_mdm_schema_endpoint_404_fallback", endpoint=endpoint)
                streams = self._get_default_streams()
            elif response.status_code in (401, 403):
                logger.error("itron_mdm_schema_auth_failed", status_code=response.status_code)
                return DiscoveredCatalogDTO.from_error(
                    connection_id,
                    AuthenticationFailedError(
                        app_id=self.app_id,
                        status_code=response.status_code,
                        message=f"Authentication failed during schema discovery: HTTP {response.status_code}",
                    ),
                )
            else:
                logger.error("itron_mdm_schema_remote_failed", status_code=response.status_code)
                return DiscoveredCatalogDTO.from_error(
                    connection_id,
                    UpstreamRemoteError(
                        status_code=response.status_code,
                        message=f"Schema discovery failed with HTTP {response.status_code}: {response.text[:200]}",
                    ),
                )
        except (HttpError, httpx.HTTPError, OSError, ValueError, KeyError) as exc:
            logger.error("itron_mdm_schema_network_failure", endpoint=endpoint, error=str(exc))
            return DiscoveredCatalogDTO.from_error(
                connection_id,
                UpstreamNetworkError(
                    endpoint=endpoint,
                    message=f"Network error during schema discovery for {endpoint}: {exc}",
                ),
            )

        return self.build_catalog_dto(connection_id, streams)

    async def list_objects(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Sequence[str]:
        endpoint_res = self._validate_endpoint(str(public_config.get("endpoint_url", "")))
        if endpoint_res.error is not None or endpoint_res.value is None:
            logger.error(
                "itron_mdm_list_objects_invalid_endpoint",
                stream_name=stream_name,
                error=endpoint_res.error.message if endpoint_res.error else "Invalid endpoint",
            )
            return []

        endpoint = endpoint_res.value
        url = f"{endpoint}/api/v1/streams/{stream_name}/ids"
        headers = self._get_headers(credentials)
        params: dict[str, str | int] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor

        try:
            resp = await self._http_client.get(
                url, headers=headers, params=params, timeout=self._timeout_seconds
            )
        except (HttpError, httpx.HTTPError, OSError) as exc:
            logger.error(
                "itron_mdm_list_objects_network_error",
                endpoint=endpoint,
                stream_name=stream_name,
                error=str(exc),
            )
            return []

        if not resp.is_success:
            logger.error(
                "itron_mdm_list_objects_failed",
                endpoint=endpoint,
                stream_name=stream_name,
                status_code=resp.status_code,
            )
            return []

        payload = resp.json()
        ids = payload.get("ids", [])
        return [str(i) for i in ids]

    async def read_stream(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        cursor: str | None = None,
        limit: int = 100,
    ) -> AsyncIterator[RecordEnvelopeDTO]:
        endpoint_res = self._validate_endpoint(str(public_config.get("endpoint_url", "")))
        if endpoint_res.error is not None or endpoint_res.value is None:
            logger.error(
                "itron_mdm_read_stream_invalid_endpoint",
                stream_name=stream_name,
                error=endpoint_res.error.message if endpoint_res.error else "Invalid endpoint",
            )
            return

        endpoint = endpoint_res.value
        url = f"{endpoint}/api/v1/streams/{stream_name}/records"
        headers = self._get_headers(credentials)
        params: dict[str, str | int] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor

        try:
            resp = await self._http_client.get(
                url, headers=headers, params=params, timeout=self._timeout_seconds
            )
        except (HttpError, httpx.HTTPError, OSError) as exc:
            logger.error(
                "itron_mdm_read_stream_network_error",
                endpoint=endpoint,
                stream_name=stream_name,
                error=str(exc),
            )
            return

        if not resp.is_success:
            logger.error(
                "itron_mdm_read_stream_failed",
                endpoint=endpoint,
                stream_name=stream_name,
                status_code=resp.status_code,
            )
            return

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
        if command.stream_name != stream_name:
            return WriteResultDTO.from_error(
                InvalidConnectionConfigError(
                    field_name="stream_name",
                    message=f"Stream name mismatch: expected '{stream_name}', got '{command.stream_name}'",
                )
            )

        endpoint_res = self._validate_endpoint(str(public_config.get("endpoint_url", "")))
        if endpoint_res.error is not None or endpoint_res.value is None:
            return WriteResultDTO.from_error(
                endpoint_res.error or InvalidEndpointError(message="Invalid endpoint_url")
            )

        endpoint = endpoint_res.value
        headers = self._get_headers(credentials)
        op = command.operation.upper()

        try:
            if op == "CREATE":
                url = f"{endpoint}/api/v1/streams/{stream_name}/records"
                resp = await self._http_client.post(
                    url, headers=headers, json=command.payload, timeout=self._timeout_seconds
                )
            elif op in ("UPDATE", "UPSERT"):
                if not command.record_id:
                    return WriteResultDTO.from_error(
                        InvalidConnectionConfigError(
                            field_name="record_id",
                            message=f"Operation '{op}' requires a record_id.",
                        )
                    )
                url = f"{endpoint}/api/v1/streams/{stream_name}/records/{command.record_id}"
                resp = await self._http_client.request(
                    "PUT", url, headers=headers, json=command.payload, timeout=self._timeout_seconds
                )
            elif op == "DELETE":
                if not command.record_id:
                    return WriteResultDTO.from_error(
                        InvalidConnectionConfigError(
                            field_name="record_id",
                            message="Operation 'DELETE' requires a record_id.",
                        )
                    )
                url = f"{endpoint}/api/v1/streams/{stream_name}/records/{command.record_id}"
                resp = await self._http_client.request(
                    "DELETE", url, headers=headers, timeout=self._timeout_seconds
                )
            else:
                return WriteResultDTO.from_error(
                    UnsupportedWriteOperationError(
                        operation=command.operation,
                        stream_name=stream_name,
                        message=f"Unsupported write operation: {command.operation}",
                    )
                )

            if not resp.is_success:
                return WriteResultDTO.from_error(
                    UpstreamHttpError(
                        status_code=resp.status_code,
                        message=f"HTTP {resp.status_code}: {resp.text}",
                    )
                )

            data = resp.json() if resp.content else {}
            return WriteResultDTO(
                success=True,
                record_id=str(data.get("id", command.record_id or "written_rec")),
                destination_id=str(data.get("destination_id", f"{self.app_id}_{stream_name}")),
            )
        except (HttpError, httpx.HTTPError, OSError, ValueError) as exc:
            return WriteResultDTO.from_error(
                UpstreamNetworkError(
                    endpoint=endpoint,
                    message=f"Network error: {exc}",
                )
            )
