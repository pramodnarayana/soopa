import hashlib
import json
from abc import ABC
from collections.abc import Sequence
from datetime import UTC, datetime

import httpx
from ip.engine.application.responses import (
    DiscoveredCatalogDTO,
    StreamSchemaDTO,
)
from ip.engine.domain.exceptions import (
    EndpointSecurityViolationError,
    InvalidConnectionConfigError,
    InvalidEndpointError,
    IpError,
    IpErrorCode,
    Result,
)
from ip.engine.ports.outbound.connector_port import ConnectorPort
from ip.engine.ports.types import RecordEnvelopeDTO
from seedwork.domain.types import JsonDict
from shttp import validate_target_url
from shttp.exceptions import SsrfSecurityError

_LOCAL_TEST_HOSTS = ("localhost", "127.0.0.1", "::1", "testserver")


class BaseConnector(ConnectorPort, ABC):
    """Abstract base connector encapsulating catalog hashing and shared URL/SSRF validation helpers."""

    @property
    def last_error(self) -> IpError | None:
        """Returns the last domain/operational error encountered during stream reading, if any."""
        return None

    @staticmethod
    def _parse_and_validate_url_structure(
        stripped: str,
        raw_endpoint: str,
        *,
        disallow_query_or_fragment: bool,
        error_code: IpErrorCode,
        field_name: str,
    ) -> Result[
        httpx.URL,
        InvalidConnectionConfigError | InvalidEndpointError | EndpointSecurityViolationError,
    ]:
        if not stripped:
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name=field_name,
                    code=error_code,
                    message=f"Missing required field: {field_name}",
                )
            )
        try:
            url = httpx.URL(stripped)
        except httpx.InvalidURL as exc:
            return Result.fail(
                InvalidEndpointError(
                    endpoint=raw_endpoint,
                    code=error_code,
                    message=f"Malformed endpoint URL: {exc}",
                )
            )
        if not url.host:
            return Result.fail(
                InvalidEndpointError(
                    endpoint=raw_endpoint,
                    code=error_code,
                    message="Endpoint URL must include a host.",
                )
            )
        if url.username or url.password:
            return Result.fail(
                EndpointSecurityViolationError(
                    endpoint=raw_endpoint,
                    code=error_code,
                    message="Endpoint URL cannot contain embedded user credentials.",
                )
            )
        if disallow_query_or_fragment and (url.query or url.fragment):
            return Result.fail(
                InvalidEndpointError(
                    endpoint=raw_endpoint,
                    code=error_code,
                    message="Endpoint URL cannot contain query or fragment parameters.",
                )
            )
        return Result.ok(url)

    @staticmethod
    def validate_http_endpoint_url(
        endpoint: str,
        *,
        allow_private_ips: bool = False,
        enforce_ssrf_precheck: bool = True,
        disallow_query_or_fragment: bool = False,
        error_code: IpErrorCode = IpErrorCode.INVALID_CONFIGURATION,
        field_name: str = "endpoint_url",
    ) -> Result[
        str,
        InvalidConnectionConfigError | InvalidEndpointError | EndpointSecurityViolationError,
    ]:
        """Centralized HTTP endpoint URL & SSRF validation shared across connectors."""
        stripped = endpoint.strip()
        parsed_res = BaseConnector._parse_and_validate_url_structure(
            stripped,
            endpoint,
            disallow_query_or_fragment=disallow_query_or_fragment,
            error_code=error_code,
            field_name=field_name,
        )
        if parsed_res.error is not None or parsed_res.value is None:
            return Result.fail(
                parsed_res.error
                or InvalidEndpointError(
                    endpoint=endpoint,
                    code=error_code,
                    message="Malformed endpoint URL.",
                )
            )

        url = parsed_res.value
        hostname = url.host.lower()
        allowed_http_hosts = (
            _LOCAL_TEST_HOSTS if (allow_private_ips or not enforce_ssrf_precheck) else ()
        )
        if url.scheme != "https" and hostname not in allowed_http_hosts:
            return Result.fail(
                EndpointSecurityViolationError(
                    endpoint=endpoint,
                    code=error_code,
                    message=f"Endpoint URL must use HTTPS: {endpoint}",
                )
            )

        if hostname.startswith("169.254."):
            return Result.fail(
                EndpointSecurityViolationError(
                    endpoint=endpoint,
                    code=error_code,
                    message="Access to link-local and cloud metadata endpoints is prohibited.",
                )
            )

        if enforce_ssrf_precheck:
            if not allow_private_ips and hostname in _LOCAL_TEST_HOSTS:
                return Result.fail(
                    EndpointSecurityViolationError(
                        endpoint=endpoint,
                        code=error_code,
                        message=f"Restricted hostname or IP address in endpoint: {hostname}",
                    )
                )
            try:
                validate_target_url(stripped, allow_private_ips=allow_private_ips)
            except SsrfSecurityError as exc:
                return Result.fail(
                    EndpointSecurityViolationError(
                        endpoint=endpoint,
                        code=error_code,
                        message=f"Restricted destination forbidden: {exc}",
                    )
                )

        return Result.ok(stripped.rstrip("/"))

    @staticmethod
    def build_catalog_dto(
        connection_id: str,
        streams: Sequence[StreamSchemaDTO],
        catalog_version: int = 1,
        discovered_at: str | None = None,
    ) -> DiscoveredCatalogDTO:
        """Helper to construct DiscoveredCatalogDTO with deterministic SHA-256 hash."""
        stream_dicts = [
            {
                "name": s.name,
                "fields": [{"name": f.name, "type": f.data_type} for f in s.fields],
                "primary_key": list(s.primary_key),
                "cursor_field": s.cursor_field,
            }
            for s in streams
        ]
        raw = json.dumps(stream_dicts, sort_keys=True)
        catalog_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

        return DiscoveredCatalogDTO(
            connection_id=connection_id,
            catalog_version=catalog_version,
            catalog_hash=catalog_hash,
            streams=streams,
            discovered_at=discovered_at or datetime.now(UTC).isoformat(),
        )

    async def fetch_record(
        self,
        stream_name: str,
        record_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> RecordEnvelopeDTO | None:
        """Default fetch_record implementation returning None when unsupported."""
        return None
